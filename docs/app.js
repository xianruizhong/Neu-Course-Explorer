/**
 * NEU Course Explorer — static GitHub Pages version
 * Fetches pre-exported JSON from data/{term}/...
 */

const DATA = "data";
const PAGE_SIZE = 50;

// ── State ──────────────────────────────────────────────────────────────────
let state = {
  term: null,
  terms: [],
  subjects: [],
  subjectData: {},    // cache: subjectCode → courses array
  searchIndex: [],    // lightweight index for the current term
  subject: "",
  query: "",
  filteredCourses: [], // current filtered+searched course list
  page: 0,
};

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const termSelect     = $("term-select");
const heroSearchForm = $("hero-search-form");
const heroInput      = $("hero-search-input");
const subjectGrid    = $("subject-grid");
const sidebarSubject = $("sidebar-subject");
const sidebarSearch  = $("sidebar-search");
const sidebarApply   = $("sidebar-apply");
const sidebarClear   = $("sidebar-clear");
const listTitle      = $("list-title");
const listCount      = $("list-count");
const courseList     = $("course-list");
const pagination     = $("pagination");
const detailContent  = $("course-detail-content");
const loading        = $("loading");
const backBtn        = $("back-btn");
const logoLink       = $("logo-link");

// ── Views ─────────────────────────────────────────────────────────────────
function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $(`view-${name}`).classList.add("active");
}

// ── Fetch helpers ──────────────────────────────────────────────────────────
async function fetchJSON(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${resp.status} ${path}`);
  return resp.json();
}

function showLoading(on) {
  loading.classList.toggle("hidden", !on);
}

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  try {
    state.terms = await fetchJSON(`${DATA}/terms.json`);
    if (!state.terms.length) {
      document.body.innerHTML = "<p style='padding:40px;color:#c8102e'>No data available yet.</p>";
      return;
    }
    termSelect.innerHTML = state.terms
      .map(t => `<option value="${t.code}">${t.description}</option>`)
      .join("");
    await selectTerm(state.terms[0].code);
  } catch (e) {
    document.body.innerHTML = `<p style='padding:40px;color:#c8102e'>Failed to load data: ${e.message}</p>`;
  }
}

async function selectTerm(code) {
  state.term = code;
  state.subjectData = {};
  state.searchIndex = [];
  showLoading(true);
  try {
    [state.subjects, state.searchIndex] = await Promise.all([
      fetchJSON(`${DATA}/${code}/subjects.json`),
      fetchJSON(`${DATA}/${code}/index.json`),
    ]);
    renderSubjectGrid();
    populateSidebarSubjects();
  } finally {
    showLoading(false);
  }
}

// ── Subject grid ───────────────────────────────────────────────────────────
function renderSubjectGrid() {
  subjectGrid.innerHTML = state.subjects.map(s => `
    <div class="subject-chip" data-code="${s.code}">
      <div class="subj-code">${s.code}</div>
      <div class="subj-name">${s.description}</div>
    </div>
  `).join("");
  subjectGrid.querySelectorAll(".subject-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      state.subject = chip.dataset.code;
      state.query = "";
      state.page = 0;
      loadCourseList();
    });
  });
}

function populateSidebarSubjects() {
  sidebarSubject.innerHTML = `<option value="">All subjects</option>` +
    state.subjects.map(s =>
      `<option value="${s.code}">${s.code} — ${s.description}</option>`
    ).join("");
}

// ── Load subject data (with cache) ─────────────────────────────────────────
async function loadSubjectData(subjectCode) {
  if (!state.subjectData[subjectCode]) {
    state.subjectData[subjectCode] = await fetchJSON(
      `${DATA}/${state.term}/${subjectCode}.json`
    );
  }
  return state.subjectData[subjectCode];
}

// ── Course list ────────────────────────────────────────────────────────────
async function loadCourseList() {
  showLoading(true);
  showView("list");

  try {
    let courses = [];

    if (state.subject) {
      // Load single subject
      courses = await loadSubjectData(state.subject);
    } else if (state.query) {
      // Search across index, then load matching subjects
      courses = await searchAllSubjects(state.query);
    } else {
      // "All subjects" with no query — show index as course-group cards
      courses = indexToCourseGroups(state.searchIndex);
    }

    // Apply query filter if we have subject + query
    if (state.subject && state.query) {
      const q = state.query.toLowerCase();
      courses = courses.filter(c =>
        (c.title || "").toLowerCase().includes(q) ||
        (c.description || "").toLowerCase().includes(q) ||
        c.course_number.includes(q)
      );
    }

    state.filteredCourses = courses;
    renderCourseList();
  } finally {
    showLoading(false);
  }
}

// Search using the lightweight index, then fetch matching subjects
async function searchAllSubjects(query) {
  const q = query.toLowerCase();
  const hits = state.searchIndex.filter(e =>
    e.t.toLowerCase().includes(q) ||
    e.d.toLowerCase().includes(q) ||
    e.s.toLowerCase().includes(q) ||
    e.n.includes(q)
  );

  // Group by subject, load only the subjects that had hits
  const subjectsNeeded = [...new Set(hits.map(h => h.s))];
  await Promise.all(subjectsNeeded.map(s => loadSubjectData(s)));

  // Return matching course objects from the loaded data
  const results = [];
  const seen = new Set();
  for (const hit of hits) {
    const key = `${hit.s}:${hit.n}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const subjectCourses = state.subjectData[hit.s] || [];
    const course = subjectCourses.find(c => c.course_number === hit.n);
    if (course) results.push(course);
  }
  return results;
}

// Convert lightweight index entries to minimal course-group objects
function indexToCourseGroups(index) {
  return index.map(e => ({
    subject: e.s,
    course_number: e.n,
    title: e.t,
    description: e.d,
    sections: [],
    _isIndexEntry: true,
  }));
}

function renderCourseList() {
  const courses = state.filteredCourses;
  const subjName = state.subject
    ? state.subjects.find(s => s.code === state.subject)?.description || state.subject
    : state.query ? `Search: "${state.query}"` : "All Courses";

  listTitle.textContent = subjName;
  listCount.textContent = `${courses.length.toLocaleString()} course${courses.length !== 1 ? "s" : ""}`;
  sidebarSubject.value = state.subject;
  sidebarSearch.value = state.query;

  if (!courses.length) {
    courseList.innerHTML = `
      <div class="empty-state">
        <h3>No courses found</h3>
        <p>Try a different subject or search term.</p>
      </div>`;
    pagination.innerHTML = "";
    return;
  }

  const start = state.page * PAGE_SIZE;
  const page = courses.slice(start, start + PAGE_SIZE);

  courseList.innerHTML = page.map(c => {
    const sectionCount = c.sections ? c.sections.length : 0;
    const credits = formatCredits(c.credit_hour_low, c.credit_hour_high);
    const snippet = (c.description || "").slice(0, 160) +
      ((c.description || "").length > 160 ? "…" : "");
    return `
      <div class="course-card" data-subject="${c.subject}" data-number="${c.course_number}">
        <div class="course-card-left">
          <div class="course-code">${c.subject} ${c.course_number}</div>
          <div class="course-title">${escHtml(c.title || "Untitled")}</div>
          <div class="course-meta">
            ${credits ? `<span>📚 ${credits} credits</span>` : ""}
            ${!c._isIndexEntry ? `<span>${sectionCount} section${sectionCount !== 1 ? "s" : ""}</span>` : ""}
          </div>
          ${snippet ? `<div class="course-desc-snippet">${escHtml(snippet)}</div>` : ""}
        </div>
        ${!c._isIndexEntry ? `
        <div class="course-card-right">
          <span class="section-count">${sectionCount} §</span>
        </div>` : ""}
      </div>`;
  }).join("");

  courseList.querySelectorAll(".course-card").forEach(card => {
    card.addEventListener("click", () =>
      loadCourseDetail(card.dataset.subject, card.dataset.number)
    );
  });

  renderPagination(courses.length);
}

function renderPagination(total) {
  const totalPages = Math.ceil(total / PAGE_SIZE);
  if (totalPages <= 1) { pagination.innerHTML = ""; return; }

  const cur = state.page;
  let btns = [];
  btns.push(pageBtn("← Prev", cur - 1, cur === 0));
  const start = Math.max(0, cur - 2);
  const end = Math.min(totalPages - 1, cur + 2);
  if (start > 0) {
    btns.push(pageBtn("1", 0, false, cur === 0));
    if (start > 1) btns.push(`<span style="padding:0 6px">…</span>`);
  }
  for (let p = start; p <= end; p++) btns.push(pageBtn(p + 1, p, false, p === cur));
  if (end < totalPages - 1) {
    if (end < totalPages - 2) btns.push(`<span style="padding:0 6px">…</span>`);
    btns.push(pageBtn(totalPages, totalPages - 1, false, cur === totalPages - 1));
  }
  btns.push(pageBtn("Next →", cur + 1, cur >= totalPages - 1));
  pagination.innerHTML = btns.join("");
  pagination.querySelectorAll("[data-page]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.page = parseInt(btn.dataset.page);
      renderCourseList();
      window.scrollTo(0, 0);
    });
  });
}

function pageBtn(label, page, disabled, active = false) {
  return `<button class="page-btn${active ? " active" : ""}" data-page="${page}"
    ${disabled ? "disabled" : ""}>${label}</button>`;
}

// ── Course detail ──────────────────────────────────────────────────────────
async function loadCourseDetail(subject, courseNumber) {
  showLoading(true);
  showView("detail");
  try {
    // Ensure subject data is loaded
    const courses = await loadSubjectData(subject);
    const course = courses.find(c => c.course_number === courseNumber);
    if (!course) {
      detailContent.innerHTML = `<p>Course not found.</p>`;
      return;
    }
    renderCourseDetail(course);
  } finally {
    showLoading(false);
  }
}

function renderCourseDetail(course) {
  const credits = formatCredits(course.credit_hour_low, course.credit_hour_high);
  const sections = course.sections || [];

  detailContent.innerHTML = `
    <div class="detail-header">
      <div class="detail-code">${course.subject} ${course.course_number}</div>
      <div class="detail-title">${escHtml(course.title || "Untitled")}</div>
      <div class="detail-meta">
        ${credits ? `<span>📚 ${credits} credit${credits !== "1" ? "s" : ""}</span>` : ""}
        <span>📋 ${sections.length} section${sections.length !== 1 ? "s" : ""}</span>
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
          ${sections.map(renderSection).join("")}
        </div>
      </div>
      <div class="detail-side"></div>
    </div>
  `;
}

function renderSection(s) {
  const pct = s.max_enrollment > 0
    ? Math.round((s.enrollment / s.max_enrollment) * 100) : 0;
  const statusBadge = s.open_section
    ? `<span class="open-badge">Open</span>`
    : `<span class="closed-badge">Closed</span>`;
  const facultyHtml = s.faculty && s.faculty.length
    ? s.faculty.map(f =>
        f.email ? `<a href="mailto:${f.email}">${escHtml(f.name || "Staff")}</a>`
                : escHtml(f.name || "Staff")
      ).join(", ")
    : "TBA";

  const meetings = (s.meetings || []).filter(m =>
    m.begin_time || m.monday || m.tuesday || m.wednesday || m.thursday || m.friday
  );
  const meetingRows = meetings.length
    ? meetings.map(m => {
        const days = [
          ["M", m.monday], ["T", m.tuesday], ["W", m.wednesday],
          ["R", m.thursday], ["F", m.friday], ["S", m.saturday],
        ].map(([d, on]) => `<span class="day ${on ? "on" : "off"}">${d}</span>`).join("");
        const time = m.begin_time && m.end_time
          ? `${fmt12(m.begin_time)} – ${fmt12(m.end_time)}` : "Time TBA";
        const loc = m.building
          ? `${m.building_desc || m.building} ${m.room || ""}`.trim() : "Location TBA";
        return `
          <div class="section-field"><label>Days</label><div class="days">${days}</div></div>
          <div class="section-field"><label>Time</label><div>${time}</div></div>
          <div class="section-field"><label>Location</label><div>${escHtml(loc)}</div></div>`;
      }).join("")
    : `<div class="section-field" style="grid-column:1/-1"><label>Schedule</label><div>TBA / Async Online</div></div>`;

  const attrTags = s.attributes && s.attributes.length
    ? `<div class="attr-tags">${s.attributes.map(a =>
        `<span class="attr-tag">${escHtml(a.description || a.code || "")}</span>`
      ).join("")}</div>` : "";

  return `
    <div class="section-card">
      <div class="section-card-header">
        <span class="section-seq">Section ${s.crn.slice(-4)}</span>
        <span class="section-crn">CRN ${s.crn}</span>
        ${statusBadge}
        ${s.campus ? `<span class="campus-badge">${escHtml(s.campus)}</span>` : ""}
        ${s.schedule_type ? `<span class="campus-badge">${escHtml(s.schedule_type)}</span>` : ""}
      </div>
      <div class="section-grid">
        ${meetingRows}
        <div class="section-field"><label>Instructor</label>
          <div class="faculty-list">${facultyHtml}</div></div>
        <div class="section-field"><label>Enrollment</label>
          <div>${s.enrollment ?? "?"} / ${s.max_enrollment ?? "?"}</div>
          <div class="enroll-bar"><div class="enroll-fill" style="width:${pct}%"></div></div>
        </div>
        ${s.wait_capacity > 0 ? `
          <div class="section-field"><label>Waitlist</label>
            <div>${s.wait_count ?? 0} / ${s.wait_capacity}</div></div>` : ""}
      </div>
      ${attrTags}
    </div>`;
}

// ── Utilities ──────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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
  return `${h > 12 ? h - 12 : h || 12}:${m} ${h >= 12 ? "PM" : "AM"}`;
}

// ── Event listeners ────────────────────────────────────────────────────────
termSelect.addEventListener("change", () => {
  selectTerm(termSelect.value);
  showView("home");
});
heroSearchForm.addEventListener("submit", e => {
  e.preventDefault();
  state.query = heroInput.value.trim();
  state.subject = "";
  state.page = 0;
  if (state.query) loadCourseList();
});
sidebarApply.addEventListener("click", () => {
  state.subject = sidebarSubject.value;
  state.query = sidebarSearch.value.trim();
  state.page = 0;
  loadCourseList();
});
sidebarClear.addEventListener("click", () => {
  state.subject = state.query = "";
  state.page = 0;
  sidebarSubject.value = "";
  sidebarSearch.value = "";
  loadCourseList();
});
backBtn.addEventListener("click", () => showView("list"));
logoLink.addEventListener("click", e => { e.preventDefault(); showView("home"); });

init();
