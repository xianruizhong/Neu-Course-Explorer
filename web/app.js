/**
 * NEU Course Explorer — single-page app
 * Talks to the FastAPI backend at /api/...
 */

const API = "/api";
const PAGE_LIMIT = 50;

// ── State ──────────────────────────────────────────────────────────────────
let state = {
  term: null,
  terms: [],
  subjects: [],
  campuses: [],
  subject: "",
  campus: "",
  query: "",
  page: 0,        // 0-indexed
  total: 0,
  detailSubject: null,
  detailNumber: null,
  detailInstructor: null,
};

let _restoring = false;

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const termSelect     = $("term-select");
const heroSearchForm = $("hero-search-form");
const heroInput      = $("hero-search-input");
const searchModeToggle = $("search-mode-toggle");
const subjectGrid    = $("subject-grid");
const alphNav        = $("alpha-nav");
const sidebarSubject = $("sidebar-subject");
const sidebarCampus  = $("sidebar-campus");
const sidebarSearch  = $("sidebar-search");
const sidebarApply   = $("sidebar-apply");
const sidebarClear   = $("sidebar-clear");
const listTitle      = $("list-title");
const listCount      = $("list-count");
const courseList     = $("course-list");
const pagination     = $("pagination");
const detailContent     = $("course-detail-content");
const instructorContent = $("instructor-content");
const instructorBackBtn = $("instructor-back-btn");
const loading           = $("loading");
const backBtn           = $("back-btn");
const logoLink          = $("logo-link");

let searchMode = "courses";

const PLACEHOLDERS = {
  courses:    "Search by course title, subject, or keyword…",
  instructor: "Search by instructor name…",
};

searchModeToggle.addEventListener("click", e => {
  const btn = e.target.closest(".mode-btn");
  if (!btn) return;
  searchMode = btn.dataset.mode;
  searchModeToggle.querySelectorAll(".mode-btn").forEach(b =>
    b.classList.toggle("active", b === btn));
  heroInput.placeholder = PLACEHOLDERS[searchMode];
  heroInput.value = "";
  heroInput.focus();
});

// ── Views ─────────────────────────────────────────────────────────────────
function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $(`view-${name}`).classList.add("active");
  if (name === "home") {
    setPageMeta(SITE_NAME, DEFAULT_DESC);
    clearJsonLd();
  }
}

// ── Routing ────────────────────────────────────────────────────────────────

// "Fall 2026 Semester" → "2026/fall",  "Summer 1 2026" → "2026/summer1"
function termDescToPath(desc) {
  const m = desc.match(/(Spring|Summer\s*\d*|Fall)\s+(\d{4})/i);
  if (!m) return null;
  return `${m[2]}/${m[1].toLowerCase().replace(/\s+/g, "")}`;
}

function currentTermPath() {
  const term = state.terms.find(t => t.code === state.term);
  return term ? termDescToPath(term.description) : "";
}

function findTermByPath(year, season) {
  return state.terms.find(t => termDescToPath(t.description) === `${year}/${season}`);
}

function subjectHref(code) {
  return `/schedule/${currentTermPath()}/${code}`;
}

function courseHref(subject, number) {
  return `/schedule/${currentTermPath()}/${subject}/${number}`;
}

function instructorHref(name) {
  return `/schedule/${currentTermPath()}/instructor/${encodeURIComponent(name)}`;
}

function writePath(view) {
  if (_restoring) return;
  const tp = currentTermPath();
  if (view === "home") { history.pushState(null, "", "/"); return; }
  if (view === "list") {
    let path = `/schedule/${tp}`;
    if (state.subject) path += `/${state.subject}`;
    const qp = new URLSearchParams();
    if (state.query) qp.set("q", state.query);
    if (state.page)  qp.set("page", state.page);
    const qs = qp.toString();
    history.pushState(null, "", path + (qs ? "?" + qs : ""));
  } else if (view === "detail") {
    history.pushState(null, "", `/schedule/${tp}/${state.detailSubject}/${state.detailNumber}`);
  } else if (view === "instructor") {
    history.pushState(null, "", `/schedule/${tp}/instructor/${encodeURIComponent(state.detailInstructor)}`);
  }
}

async function restoreFromPath() {
  const pathname = location.pathname;
  const params   = new URLSearchParams(location.search);
  const m = pathname.match(/^\/schedule\/(\d{4})\/([^/]+)(\/.*)?$/);
  if (!m) { showView("home"); return; }
  const [, year, season, rest] = m;

  _restoring = true;
  try {
    const term = findTermByPath(year, season);
    if (!term) { showView("home"); return; }
    if (term.code !== state.term) {
      termSelect.value = term.code;
      await selectTerm(term.code);
    }
    if (!rest || rest === "/") {
      const q = params.get("q");
      if (q) {
        state.subject = "";
        state.query   = q;
        state.page    = parseInt(params.get("page") || "0", 10);
        await loadCourseList();
      } else {
        showView("home");
      }
    } else {
      const segs = rest.slice(1).split("/").filter(Boolean);
      if (segs[0] === "instructor") {
        await loadInstructorSections(decodeURIComponent(segs.slice(1).join("/")));
      } else if (segs.length === 1) {
        state.subject = segs[0].toUpperCase();
        state.query   = params.get("q") || "";
        state.page    = parseInt(params.get("page") || "0", 10);
        await loadCourseList();
      } else if (segs.length >= 2) {
        await loadCourseDetail(segs[0].toUpperCase(), segs[1]);
      }
    }
  } finally {
    _restoring = false;
  }
}

// ── API helpers ────────────────────────────────────────────────────────────
async function apiFetch(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${path}`);
  return resp.json();
}

function showLoading(on) {
  loading.classList.toggle("hidden", !on);
}

// ── Initialise ─────────────────────────────────────────────────────────────
async function init() {
  try {
    state.terms = await apiFetch(`${API}/terms`);
    if (!state.terms.length) {
      document.body.innerHTML = "<p style='padding:40px;color:#c8102e'>No data scraped yet. Run the scraper first.</p>";
      return;
    }
    populateTermSelect();

    const pathMatch = location.pathname.match(/^\/schedule\/(\d{4})\/([^/]+)/);
    const pathTerm  = pathMatch ? state.terms.find(
      t => termDescToPath(t.description) === `${pathMatch[1]}/${pathMatch[2]}`
    ) : null;
    const initialTerm = pathTerm ? pathTerm.code : state.terms[0].code;
    termSelect.value = initialTerm;
    await selectTerm(initialTerm);

    if (location.pathname.startsWith("/schedule/")) {
      await restoreFromPath();
    } else {
      showView("home");
    }
  } catch (e) {
    document.body.innerHTML = `<p style='padding:40px;color:#c8102e'>Could not connect to API: ${e.message}</p>`;
  }
}

function populateTermSelect() {
  termSelect.innerHTML = state.terms
    .map(t => `<option value="${t.code}">${t.description}</option>`)
    .join("");
}

async function selectTerm(code) {
  state.term = code;
  showLoading(true);
  try {
    [state.subjects, state.campuses] = await Promise.all([
      apiFetch(`${API}/terms/${code}/subjects`),
      apiFetch(`${API}/terms/${code}/campuses`),
    ]);
    renderSubjectGrid();
    populateSidebarSubjects();
    populateSidebarCampuses();
  } finally {
    showLoading(false);
  }
}

// ── Subject grid (home) ────────────────────────────────────────────────────
function renderSubjectGrid() {
  const groups = {};
  state.subjects.forEach(s => {
    const letter = s.code[0].toUpperCase();
    if (!groups[letter]) groups[letter] = [];
    groups[letter].push(s);
  });
  const presentLetters = new Set(Object.keys(groups));
  const allLetters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

  alphNav.innerHTML = allLetters.map(l =>
    presentLetters.has(l)
      ? `<a class="alpha-btn" href="#subj-letter-${l}" data-letter="${l}">${l}</a>`
      : `<span class="alpha-btn alpha-btn--off">${l}</span>`
  ).join("");

  alphNav.querySelectorAll(".alpha-btn[data-letter]").forEach(btn => {
    btn.addEventListener("click", e => {
      e.preventDefault();
      const target = document.getElementById(`subj-letter-${btn.dataset.letter}`);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  subjectGrid.innerHTML = Object.keys(groups).sort().map(letter => `
    <div class="subj-letter-header" id="subj-letter-${letter}">${letter}</div>
    ${groups[letter].map(s => `
      <a class="subject-chip" href="${subjectHref(s.code)}" data-code="${s.code}">
        <div class="subj-code">${s.code}</div>
        <div class="subj-name">${escHtml(s.description)}</div>
      </a>
    `).join("")}
  `).join("");

  subjectGrid.querySelectorAll(".subject-chip").forEach(chip => {
    chip.addEventListener("click", e => {
      e.preventDefault();
      state.subject = chip.dataset.code;
      state.query = "";
      state.page = 0;
      loadCourseList();
    });
  });
}

function populateSidebarSubjects() {
  sidebarSubject.innerHTML = `<option value="">All subjects</option>` +
    state.subjects.map(s => `<option value="${s.code}">${s.code} — ${s.description}</option>`).join("");
}

function populateSidebarCampuses() {
  sidebarCampus.innerHTML = `<option value="">All campuses</option>` +
    state.campuses.map(c => `<option value="${c}">${escHtml(c)}</option>`).join("");
}

// ── Course list ────────────────────────────────────────────────────────────
async function loadCourseList() {
  showLoading(true);
  showView("list");
  writePath("list");
  try {
    const params = new URLSearchParams({
      offset: state.page * PAGE_LIMIT,
      limit: PAGE_LIMIT,
    });
    if (state.subject) params.set("subject", state.subject);
    if (state.campus)  params.set("campus", state.campus);
    if (state.query)   params.set("q", state.query);

    const data = await apiFetch(`${API}/terms/${state.term}/courses?${params}`);
    state.total = data.total;
    renderCourseList(data);
  } finally {
    showLoading(false);
  }
}

function renderCourseList(data) {
  // Title
  const subjName = state.subject
    ? state.subjects.find(s => s.code === state.subject)?.description || state.subject
    : "All Courses";
  listTitle.textContent = subjName;
  listCount.textContent = `${data.total.toLocaleString()} course${data.total !== 1 ? "s" : ""}`;

  const listDesc = state.query
    ? `${data.total} Northeastern courses matching "${state.query}"`
    : state.subject
      ? `${data.total} courses in ${subjName} at Northeastern University`
      : `Browse all ${data.total} Northeastern University courses`;
  setPageMeta(state.query ? `Search: ${state.query}` : subjName, listDesc);
  clearJsonLd();

  // Sync sidebar
  sidebarSubject.value = state.subject;
  sidebarCampus.value  = state.campus;
  sidebarSearch.value  = state.query;

  if (!data.results.length) {
    courseList.innerHTML = `
      <div class="empty-state">
        <h3>No courses found</h3>
        <p>Try a different subject or search term.</p>
      </div>`;
    pagination.innerHTML = "";
    return;
  }

  courseList.innerHTML = data.results.map(c => {
    const credits = formatCredits(c.credit_hour_low, c.credit_hour_high);
    const snippet = c.description
      ? c.description.slice(0, 160) + (c.description.length > 160 ? "…" : "")
      : "";
    return `
      <a class="course-card" href="${courseHref(c.subject, c.course_number)}" data-subject="${c.subject}" data-number="${c.course_number}">
        <div class="course-card-left">
          <div class="course-code">${c.subject} ${c.course_number}</div>
          <div class="course-title">${escHtml(c.title || "Untitled")}</div>
          <div class="course-meta">
            ${credits ? `<span>📚 ${credits} credits</span>` : ""}
            <span>${c.section_count} section${c.section_count !== 1 ? "s" : ""}</span>
          </div>
          ${snippet ? `<div class="course-desc-snippet">${escHtml(snippet)}</div>` : ""}
        </div>
        <div class="course-card-right">
          <span class="section-count">${c.section_count} §</span>
        </div>
      </a>`;
  }).join("");

  courseList.querySelectorAll(".course-card").forEach(card => {
    card.addEventListener("click", e => {
      e.preventDefault();
      loadCourseDetail(card.dataset.subject, card.dataset.number);
    });
  });

  renderPagination(data.total);
}

function renderPagination(total) {
  const totalPages = Math.ceil(total / PAGE_LIMIT);
  if (totalPages <= 1) { pagination.innerHTML = ""; return; }

  const cur = state.page;
  let btns = [];

  btns.push(pageBtn("← Prev", cur - 1, cur === 0));
  // Show window of pages
  const start = Math.max(0, cur - 2);
  const end   = Math.min(totalPages - 1, cur + 2);
  if (start > 0) {
    btns.push(pageBtn("1", 0, false, 0 === cur));
    if (start > 1) btns.push(`<span style="padding:0 4px;align-self:center">…</span>`);
  }
  for (let p = start; p <= end; p++) {
    btns.push(pageBtn(p + 1, p, false, p === cur));
  }
  if (end < totalPages - 1) {
    if (end < totalPages - 2) btns.push(`<span style="padding:0 4px;align-self:center">…</span>`);
    btns.push(pageBtn(totalPages, totalPages - 1, false, totalPages - 1 === cur));
  }
  btns.push(pageBtn("Next →", cur + 1, cur >= totalPages - 1));

  pagination.innerHTML = btns.join("");
  pagination.querySelectorAll("[data-page]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.page = parseInt(btn.dataset.page);
      loadCourseList();
      window.scrollTo(0, 0);
    });
  });
}

function pageBtn(label, page, disabled, active = false) {
  return `<button class="page-btn${active ? " active" : ""}"
    data-page="${page}" ${disabled ? "disabled" : ""}>${label}</button>`;
}

// ── Course detail ──────────────────────────────────────────────────────────
async function loadCourseDetail(subject, courseNumber) {
  state.detailSubject = subject;
  state.detailNumber = courseNumber;
  showLoading(true);
  showView("detail");
  writePath("detail");
  try {
    const [course, sections] = await Promise.all([
      apiFetch(`${API}/terms/${state.term}/courses/${subject}/${courseNumber}`),
      apiFetch(`${API}/terms/${state.term}/courses/${subject}/${courseNumber}/sections`),
    ]);
    renderCourseDetail(course, sections);
  } finally {
    showLoading(false);
  }
}

function groupSectionsByTitle(sections) {
  const map = new Map();
  for (const s of sections) {
    const key = s.title || "";
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(s);
  }
  return [...map.entries()].map(([title, secs], i) => ({ title, secs, id: `sg-${i}` }));
}

function renderCourseDetail(course, sections) {
  const courseLabel = `${course.subject} ${course.course_number}`;
  const courseTitle = course.title || "Untitled";
  const metaDesc = course.description
    ? course.description.slice(0, 200)
    : `${courseLabel} at Northeastern University — ${sections.length} section${sections.length !== 1 ? "s" : ""} offered`;
  setPageMeta(`${courseLabel}: ${courseTitle}`, metaDesc);
  setJsonLd({
    "@context": "https://schema.org",
    "@type": "Course",
    "name": courseTitle,
    "courseCode": courseLabel,
    "description": metaDesc,
    "provider": {
      "@type": "CollegeOrUniversity",
      "name": "Northeastern University",
      "sameAs": "https://www.northeastern.edu"
    }
  });

  const credits = formatCredits(course.credit_hour_low, course.credit_hour_high);
  const groups = groupSectionsByTitle(sections);

  const sectionsHtml = groups.map(({ title, secs, id }) => `
    ${title ? `<h4 class="section-group-title" id="${id}">${escHtml(title)}</h4>` : ""}
    ${secs.map(s => renderSection(s, true)).join("")}
  `).join("");

  const sidebarHtml = `
    <div class="detail-toc">
      <div class="detail-toc-label">Sections</div>
      <ul class="detail-toc-list">
        ${groups.map(({ title, secs, id }) => `
          <li>
            <a class="toc-link" href="javascript:void(0)" data-target="${id}">${escHtml(title || "Untitled")}</a>
            <span class="toc-count">${secs.length}</span>
          </li>`).join("")}
      </ul>
    </div>`;

  detailContent.innerHTML = `
    <div class="detail-header">
      <div class="detail-code">${course.subject} ${course.course_number}</div>
      <div class="detail-title">${escHtml(course.title || "Untitled")}</div>
      <div class="detail-meta">
        ${credits ? `<span>📚 ${credits} credit${credits !== "1" ? "s" : ""}</span>` : ""}
        <span>📋 ${course.section_count} section${course.section_count !== 1 ? "s" : ""}</span>
      </div>
    </div>

    <div class="detail-body">
      <div class="detail-main">
        ${course.description ? `
          <div class="detail-desc">
            <h3>Description</h3>
            <p>${escHtml(course.description)}</p>
          </div>` : ""}
        ${course.prerequisites ? `
          <div class="detail-prereqs">
            <h3>Prerequisites</h3>
            <p>${escHtml(course.prerequisites)}</p>
          </div>` : ""}
        <div class="sections-wrap">
          <h3>${sections.length} Section${sections.length !== 1 ? "s" : ""}</h3>
          ${sectionsHtml}
        </div>
      </div>
      <div class="detail-side">
        ${sidebarHtml}
      </div>
    </div>
  `;

  detailContent.querySelectorAll(".toc-link[data-target]").forEach(link => {
    link.addEventListener("click", () => {
      const target = document.getElementById(link.dataset.target);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function renderSection(s, hideTitle = false) {
  const pct = s.max_enrollment > 0
    ? Math.round((s.enrollment / s.max_enrollment) * 100)
    : 0;
  const statusBadge = s.open_section
    ? `<span class="open-badge">Open</span>`
    : `<span class="closed-badge">Closed</span>`;

  const facultyHtml = s.faculty.length
    ? s.faculty.map(f => {
        const nameLink = f.name
          ? `<a class="instructor-link" href="${instructorHref(f.name)}" data-instructor="${escHtml(f.name)}">${escHtml(f.name)}</a>`
          : "Staff";
        const emailLink = f.email ? ` <a href="mailto:${f.email}" title="${escHtml(f.email)}">✉</a>` : "";
        return nameLink + emailLink;
      }).join(", ")
    : "TBA";

  const meetings = s.meetings.filter(m => m.begin_time || m.monday || m.tuesday ||
    m.wednesday || m.thursday || m.friday);

  const meetingRows = meetings.length
    ? meetings.map(m => {
        const days = [
          ["M", m.monday], ["T", m.tuesday], ["W", m.wednesday],
          ["R", m.thursday], ["F", m.friday], ["S", m.saturday],
        ].map(([d, on]) => `<span class="day ${on ? "on" : "off"}">${d}</span>`).join("");

        const time = (m.begin_time && m.end_time)
          ? `${fmt12(m.begin_time)} – ${fmt12(m.end_time)}`
          : "Time TBA";
        const loc = m.building
          ? `${m.building_desc || m.building} ${m.room || ""}`.trim()
          : "Location TBA";
        return `
          <div class="meeting-row">
            <div class="section-field">
              <label>Days</label>
              <div class="days">${days}</div>
            </div>
            <div class="section-field">
              <label>Time</label>
              <div>${time}</div>
            </div>
            <div class="section-field">
              <label>Location</label>
              <div>${escHtml(loc)}</div>
            </div>
          </div>`;
      }).join("")
    : `<div class="section-field" style="grid-column:1/-1"><label>Schedule</label><div>TBA / Async Online</div></div>`;

  const attrTags = s.attributes.length
    ? `<div class="attr-tags">${s.attributes.map(a =>
        `<span class="attr-tag" title="${escHtml(a.code || "")}">${escHtml(a.description || a.code || "")}</span>`
      ).join("")}</div>`
    : "";

  return `
    <div class="section-card">
      <div class="section-card-header">
        <span class="section-seq">Section ${escHtml(s.sequence_number ?? s.crn.slice(-4))}</span>
        <span class="section-crn">CRN ${s.crn}</span>
        ${statusBadge}
        ${s.campus ? `<span class="campus-badge">${escHtml(s.campus)}</span>` : ""}
        ${s.schedule_type ? `<span class="campus-badge">${escHtml(s.schedule_type)}</span>` : ""}
      </div>
      ${(!hideTitle && s.title) ? `<div class="section-title">${escHtml(s.title)}</div>` : ""}

      <div class="section-grid">
        ${meetingRows}
        <div class="section-field">
          <label>Instructor</label>
          <div class="faculty-list">${facultyHtml}</div>
        </div>
        ${(s.credit_hour_low || s.credit_hour_high) ? `
        <div class="section-field">
          <label>Credits</label>
          <div>${formatCredits(s.credit_hour_low, s.credit_hour_high)}</div>
        </div>` : ""}
        <div class="section-field">
          <label>Enrollment</label>
          <div>${s.enrollment ?? "?"} / ${s.max_enrollment ?? "?"}</div>
          <div class="enroll-bar">
            <div class="enroll-fill" style="width:${pct}%"></div>
          </div>
        </div>
        ${s.wait_capacity > 0 ? `
          <div class="section-field">
            <label>Waitlist</label>
            <div>${s.wait_count ?? 0} / ${s.wait_capacity}</div>
          </div>` : ""}
      </div>
      ${attrTags}
    </div>`;
}

// ── SEO helpers ────────────────────────────────────────────────────────────
const SITE_NAME = "NEU Course Explorer";
const DEFAULT_DESC = "Browse Northeastern University courses, sections, real-time enrollment, instructors, and prerequisites across all terms.";

function setPageMeta(title, description = DEFAULT_DESC) {
  document.title = title === SITE_NAME ? title : `${title} — ${SITE_NAME}`;
  const full = title === SITE_NAME ? title : `${title} — ${SITE_NAME}`;
  [
    ['meta[name="description"]',       "content",  description],
    ['meta[property="og:title"]',      "content",  full],
    ['meta[property="og:description"]',"content",  description],
    ['meta[name="twitter:title"]',     "content",  full],
    ['meta[name="twitter:description"]',"content", description],
  ].forEach(([sel, attr, val]) => {
    const el = document.querySelector(sel);
    if (el) el.setAttribute(attr, val);
  });
}

function setJsonLd(data) {
  let el = document.getElementById("_json-ld-dynamic");
  if (!el) {
    el = document.createElement("script");
    el.id = "_json-ld-dynamic";
    el.type = "application/ld+json";
    document.head.appendChild(el);
  }
  el.textContent = JSON.stringify(data);
}

function clearJsonLd() {
  document.getElementById("_json-ld-dynamic")?.remove();
}

// ── Utilities ──────────────────────────────────────────────────────────────
const _decodeEl = document.createElement("textarea");
function escHtml(str) {
  if (!str) return "";
  _decodeEl.innerHTML = String(str);
  const decoded = _decodeEl.value;
  return decoded
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatCredits(low, high) {
  if (!low && !high) return null;
  if (low === high || !high) return String(low ?? high);
  return `${low}–${high}`;
}

function fmt12(t) {
  if (!t) return "";
  const h = parseInt(t.slice(0, 2), 10);
  const m = t.slice(2, 4);
  const ampm = h >= 12 ? "PM" : "AM";
  return `${h > 12 ? h - 12 : h || 12}:${m} ${ampm}`;
}

// ── Instructor search ──────────────────────────────────────────────────────
async function loadInstructorSections(name) {
  state.detailInstructor = name;
  showLoading(true);
  showView("instructor");
  writePath("instructor");
  try {
    const sections = await apiFetch(
      `${API}/terms/${state.term}/instructors/${encodeURIComponent(name)}/sections`
    );
    renderInstructorView(name, sections);
  } catch (e) {
    instructorContent.innerHTML = `<p class="empty-state">No sections found for "${escHtml(name)}".</p>`;
  } finally {
    showLoading(false);
  }
}

function renderInstructorView(name, sections) {
  const termDesc = state.terms.find(t => t.code === state.term)?.description || state.term;
  setPageMeta(`Instructor: ${name}`, `${sections.length} section${sections.length !== 1 ? "s" : ""} taught by ${name} at Northeastern University in ${termDesc}.`);
  clearJsonLd();

  // Group sections by course
  const groups = new Map();
  for (const s of sections) {
    const key = `${s.subject}|${s.course_number}`;
    if (!groups.has(key)) groups.set(key, { subject: s.subject, course_number: s.course_number, title: s.title, sections: [] });
    groups.get(key).sections.push(s);
  }

  const groupsHtml = [...groups.values()].map(g => `
    <div class="instructor-course-group">
      <h3 class="instructor-course-header">
        <a class="instructor-course-link" href="${courseHref(g.subject, g.course_number)}" data-subject="${escHtml(g.subject)}" data-number="${escHtml(g.course_number)}">${escHtml(g.subject)} ${escHtml(g.course_number)}</a>
        <span class="instructor-course-title">— ${escHtml(g.title || "")}</span>
      </h3>
      ${g.sections.map(renderSection).join("")}
    </div>
  `).join("");

  instructorContent.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">Instructor: ${escHtml(name)}</div>
      <div class="detail-meta">
        <span>${sections.length} section${sections.length !== 1 ? "s" : ""} in ${escHtml(termDesc)}</span>
      </div>
    </div>
    ${groupsHtml || '<p class="empty-state">No sections found.</p>'}
  `;
  instructorContent.querySelectorAll(".instructor-course-link").forEach(link => {
    link.addEventListener("click", e => {
      e.preventDefault();
      loadCourseDetail(link.dataset.subject, link.dataset.number);
    });
  });
}

// ── Event listeners ────────────────────────────────────────────────────────
termSelect.addEventListener("change", () => {
  selectTerm(termSelect.value);
  history.pushState(null, "", "/");
  showView("home");
});

heroSearchForm.addEventListener("submit", e => {
  e.preventDefault();
  const val = heroInput.value.trim();
  if (!val) return;
  if (searchMode === "instructor") {
    loadInstructorSections(val);
  } else {
    state.query   = val;
    state.subject = "";
    state.page    = 0;
    loadCourseList();
  }
});

sidebarApply.addEventListener("click", () => {
  state.subject = sidebarSubject.value;
  state.campus  = sidebarCampus.value;
  state.query   = sidebarSearch.value.trim();
  state.page    = 0;
  loadCourseList();
});

sidebarClear.addEventListener("click", () => {
  state.subject = "";
  state.campus  = "";
  state.query   = "";
  state.page    = 0;
  sidebarSubject.value = "";
  sidebarCampus.value  = "";
  sidebarSearch.value  = "";
  loadCourseList();
});

backBtn.addEventListener("click", () => {
  history.back();
});

instructorBackBtn.addEventListener("click", () => {
  history.back();
});

document.addEventListener("click", e => {
  const link = e.target.closest(".instructor-link");
  if (link) {
    e.preventDefault();
    loadInstructorSections(link.dataset.instructor);
  }
});

logoLink.addEventListener("click", e => {
  e.preventDefault();
  history.pushState(null, "", "/");
  showView("home");
});

window.addEventListener("popstate", () => {
  restoreFromPath();
});

// ── Boot ───────────────────────────────────────────────────────────────────
init();
