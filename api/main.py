"""
NEU Course Explorer — FastAPI backend
Serves course data from PostgreSQL (connection string via DATABASE_URL).
"""

import html as _html
import json
import logging
import os
import re
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL", "")
SITE_URL = "https://neu-course-explorer.vercel.app"
SITE_NAME = "NEU Course Explorer"
DEFAULT_DESC = "Browse Northeastern University courses, sections, real-time enrollment, instructors, and prerequisites across all terms."
_TERM_PATH_RE = re.compile(r'(Spring|Summer\s*\d*|Fall)\s+(\d{4})', re.IGNORECASE)


def _term_desc_to_path(desc: str) -> str | None:
    m = _TERM_PATH_RE.search(desc)
    if not m:
        return None
    return f"{m.group(2)}/{re.sub(r'\s+', '', m.group(1).lower())}"

# Matches "CS 1800", "cs1800", "EECE 2322" etc.
_COURSE_CODE_RE = re.compile(r'^\s*([A-Za-z]+)\s*(\d+[A-Za-z]?)\s*$')

app = FastAPI(title="NEU Course Explorer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def fetchall(conn, sql: str, params=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetchone(conn, sql: str, params=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def row_to_dict(row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class Term(BaseModel):
    code: str
    description: str


class Subject(BaseModel):
    code: str
    description: str


class MeetingTime(BaseModel):
    begin_time: Optional[str]
    end_time: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    building: Optional[str]
    building_desc: Optional[str]
    room: Optional[str]
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    schedule_type: Optional[str]


class FacultyMember(BaseModel):
    name: Optional[str]
    email: Optional[str]
    primary_ind: bool


class SectionAttribute(BaseModel):
    code: Optional[str]
    description: Optional[str]


class CourseSection(BaseModel):
    crn: str
    term_code: str
    subject: str
    subject_description: Optional[str]
    course_number: str
    title: Optional[str]
    credit_hour_low: Optional[float]
    credit_hour_high: Optional[float]
    campus: Optional[str]
    schedule_type: Optional[str]
    part_of_term: Optional[str]
    enrollment: Optional[int]
    max_enrollment: Optional[int]
    seats_available: Optional[int]
    wait_count: Optional[int]
    wait_capacity: Optional[int]
    wait_available: Optional[int]
    open_section: bool
    description: Optional[str]
    prerequisites: Optional[str]
    scraped_at: Optional[str]
    sequence_number: Optional[str]
    meetings: list[MeetingTime] = []
    faculty: list[FacultyMember] = []
    attributes: list[SectionAttribute] = []


class CourseGroup(BaseModel):
    subject: str
    subject_description: Optional[str]
    course_number: str
    title: Optional[str]
    course_title: Optional[str]
    credit_hour_low: Optional[float]
    credit_hour_high: Optional[float]
    description: Optional[str]
    prerequisites: Optional[str]
    section_count: int


class SearchResult(BaseModel):
    total: int
    offset: int
    limit: int
    results: list[CourseGroup]


class InstructorSummary(BaseModel):
    name: str
    email: Optional[str]
    section_count: int


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _spa_html(*, page_title=SITE_NAME, description=DEFAULT_DESC,
              canonical=SITE_URL, json_ld: dict | None = None,
              active_view: str = "home", detail_html: str = "") -> str:
    full_title = page_title if page_title == SITE_NAME else f"{page_title} — {SITE_NAME}"
    esc = _html.escape
    json_ld_tag = (
        f'<script type="application/ld+json">{json.dumps(json_ld)}</script>'
        if json_ld else ""
    )
    home_active   = " active" if active_view == "home"   else ""
    detail_active = " active" if active_view == "detail" else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
  <base href="/" />
  <title>{esc(full_title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="NEU Course Explorer">
  <meta property="og:title" content="{esc(full_title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="{esc(full_title)}">
  <meta name="twitter:description" content="{esc(description)}">
  {json_ld_tag}
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preload" href="style.css" as="style" onload="this.onload=null;this.rel='stylesheet'">
  <noscript><link rel="stylesheet" href="style.css"></noscript>
</head>
<body>
  <header>
    <div class="header-inner">
      <a href="#" class="logo" id="logo-link">
        <span class="logo-neu">NEU</span>
        <span class="logo-text">Course Explorer</span>
      </a>
      <nav class="header-nav">
        <select id="term-select" class="term-selector" title="Select term"></select>
      </nav>
    </div>
  </header>
  <div id="view-home" class="view{home_active}">
    <section class="hero">
      <h1>Explore Northeastern University Courses</h1>
      <p class="hero-sub">Search the full course catalog with sections, enrollment, and prerequisites.</p>
      <div class="search-mode-toggle" id="search-mode-toggle">
        <button type="button" class="mode-btn active" data-mode="courses">Courses</button>
        <button type="button" class="mode-btn" data-mode="instructor">Instructor</button>
      </div>
      <form class="hero-search" id="hero-search-form">
        <input type="text" id="hero-search-input" placeholder="Search by course title, subject, or keyword…" autocomplete="off" />
        <button type="submit">Search</button>
      </form>
      <div class="alpha-nav" id="alpha-nav"></div>
      <div class="subject-grid" id="subject-grid"></div>
    </section>
    <section class="about-section">
      <h2>About NEU Course Explorer</h2>
      <p>NEU Course Explorer is a free, fast, ad-free way to browse Northeastern University's full course catalog. Data comes directly from Northeastern's Banner registration system, so you can see real-time enrollment counts, available seats, waitlist status, meeting times, instructor assignments, and prerequisites for every course offered each term — across the Boston, Oakland, Vancouver, London, Toronto, and online campuses.</p>
      <p><a href="/subjects">Browse all subjects</a> to see the full list of departments and the courses offered in each.</p>
      <h3>What you can do here</h3>
      <ul>
        <li>Browse every course by subject — Computer Science, Mathematics, Mechanical Engineering, Accounting, Biology, and more than a hundred other departments.</li>
        <li>Search by course title, course code, or keyword. Try queries like <em>data structures</em>, <em>CS 2500</em>, or <em>organic chemistry</em>.</li>
        <li>Look up an instructor to find every section they are teaching in the selected term.</li>
        <li>Filter the catalog by campus to find in-person, fully online, hybrid, or co-op friendly course options.</li>
        <li>See at a glance which sections are open, closed, or have waitlist availability before you register.</li>
        <li>Read full course descriptions and prerequisite chains so you can plan your degree and electives confidently.</li>
      </ul>
      <h3>What's on each course page</h3>
      <p>Every course page groups its sections by type — Lecture, Recitation, Lab, Seminar, Studio, or Practicum — and lists CRN numbers, meeting days and times, room locations, faculty contact information, credit hours, and current enrollment versus maximum capacity. Sections are kept up to date from the official Banner feed, so the seat counts you see here closely track what students see inside the registration portal.</p>
      <h3>Who is this for?</h3>
      <p>Whether you are a current Northeastern student building next semester's schedule, a prospective applicant exploring what the university offers, a faculty member curious about other departments, or an alum keeping tabs on new courses, NEU Course Explorer makes it easy to navigate the catalog without signing in or clicking through Banner's registration screens.</p>
      <p class="about-disclaimer">This is an unofficial, student-built resource and is not affiliated with or endorsed by Northeastern University. For official course registration, please use the Northeastern Student Hub.</p>
    </section>
  </div>
  <div id="view-list" class="view">
    <div class="list-layout">
      <aside class="sidebar">
        <h3>Filter</h3>
        <label for="sidebar-subject">Subject</label>
        <select id="sidebar-subject"><option value="">All subjects</option></select>
        <label for="sidebar-campus" style="margin-top:12px">Campus</label>
        <select id="sidebar-campus"><option value="">All campuses</option></select>
        <label for="sidebar-search" style="margin-top:12px">Search</label>
        <input type="text" id="sidebar-search" placeholder="Keyword…" />
        <button id="sidebar-apply" class="btn-primary" style="margin-top:12px;width:100%">Apply</button>
        <button id="sidebar-clear" class="btn-ghost" style="margin-top:6px;width:100%">Clear</button>
      </aside>
      <main class="course-main">
        <div class="list-header">
          <h2 id="list-title">Courses</h2>
          <span id="list-count" class="count-badge"></span>
        </div>
        <div id="course-list" class="course-cards"></div>
        <div id="pagination" class="pagination"></div>
      </main>
    </div>
  </div>
  <div id="view-instructor" class="view">
    <div class="detail-layout">
      <button class="back-btn" id="instructor-back-btn">← Back to courses</button>
      <div id="instructor-content"></div>
    </div>
  </div>
  <div id="view-detail" class="view{detail_active}">
    <div class="detail-layout">
      <button class="back-btn" id="back-btn">← Back to courses</button>
      <div id="course-detail-content">{detail_html}</div>
    </div>
  </div>
  <div id="loading" class="loading-overlay hidden"><div class="spinner"></div></div>
  <footer class="site-footer">
    <a href="https://xianruizhong.github.io/" target="_blank" rel="noopener noreferrer" class="footer-link">Xianrui Zhong</a>
    <span class="footer-sep">·</span>
    <a href="https://github.com/xianruizhong/Neu-Course-Explorer" target="_blank" rel="noopener noreferrer" class="footer-link footer-github-link">GitHub</a>
  </footer>
  <script src="app.js"></script>
  <script defer src="/_vercel/insights/script.js"></script>
</body>
</html>"""


def _404_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
  <title>Page not found — NEU Course Explorer</title>
  <meta name="description" content="The page you're looking for doesn't exist.">
  <meta name="robots" content="noindex">
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <div class="header-inner">
      <a href="/" class="logo">
        <span class="logo-neu">NEU</span>
        <span class="logo-text">Course Explorer</span>
      </a>
    </div>
  </header>
  <main class="not-found">
    <div class="not-found-code">404</div>
    <h1 class="not-found-title">Page not found</h1>
    <p class="not-found-desc">The page you're looking for doesn't exist or has been moved.</p>
    <a class="btn-primary not-found-cta" href="/">Back to home</a>
  </main>
  <footer class="site-footer">
    <a href="https://xianruizhong.github.io/" target="_blank" rel="noopener noreferrer" class="footer-link">Xianrui Zhong</a>
    <span class="footer-sep">·</span>
    <a href="https://github.com/xianruizhong/Neu-Course-Explorer" target="_blank" rel="noopener noreferrer" class="footer-link">GitHub</a>
  </footer>
</body>
</html>"""


def _error_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
  <title>Something went wrong — NEU Course Explorer</title>
  <meta name="description" content="An error occurred while loading this page.">
  <meta name="robots" content="noindex">
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <div class="header-inner">
      <a href="/" class="logo">
        <span class="logo-neu">NEU</span>
        <span class="logo-text">Course Explorer</span>
      </a>
    </div>
  </header>
  <main class="not-found">
    <div class="not-found-code">500</div>
    <h1 class="not-found-title">Something went wrong</h1>
    <p class="not-found-desc">We couldn't load this page right now. Please try again in a moment.</p>
    <a class="btn-primary not-found-cta" href="/">Back to home</a>
  </main>
  <footer class="site-footer">
    <a href="https://xianruizhong.github.io/" target="_blank" rel="noopener noreferrer" class="footer-link">Xianrui Zhong</a>
    <span class="footer-sep">·</span>
    <a href="https://github.com/xianruizhong/Neu-Course-Explorer" target="_blank" rel="noopener noreferrer" class="footer-link">GitHub</a>
  </footer>
</body>
</html>"""


def _directory_html(*, page_title: str, description: str, canonical: str,
                    h1: str, intro_html: str, body_html: str) -> str:
    full_title = f"{page_title} — {SITE_NAME}"
    esc = _html.escape
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
  <title>{esc(full_title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="NEU Course Explorer">
  <meta property="og:title" content="{esc(full_title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <div class="header-inner">
      <a href="/" class="logo">
        <span class="logo-neu">NEU</span>
        <span class="logo-text">Course Explorer</span>
      </a>
    </div>
  </header>
  <main class="directory">
    <h1>{esc(h1)}</h1>
    {intro_html}
    {body_html}
  </main>
  <footer class="site-footer">
    <a href="https://xianruizhong.github.io/" target="_blank" rel="noopener noreferrer" class="footer-link">Xianrui Zhong</a>
    <span class="footer-sep">·</span>
    <a href="https://github.com/xianruizhong/Neu-Course-Explorer" target="_blank" rel="noopener noreferrer" class="footer-link">GitHub</a>
  </footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/schedule/{year}/{season}/{subject}/{course_number}", response_class=HTMLResponse)
def course_page(year: str, season: str, subject: str, course_number: str):
    canonical = f"{SITE_URL}/schedule/{year}/{season}/{subject}/{course_number}"
    try:
        with get_db() as db:
            terms = fetchall(db, "SELECT code, description FROM terms ORDER BY code DESC")
        term = next(
            (t for t in terms if _term_desc_to_path(t["description"]) == f"{year}/{season}"),
            None,
        )
        if not term:
            return HTMLResponse(_404_html(), status_code=404)
        with get_db() as db:
            row = fetchone(
                db,
                """SELECT subject, course_number,
                          MAX(course_title)     AS title,
                          MAX(description)      AS description,
                          MAX(prerequisites)    AS prerequisites,
                          MAX(credit_hour_low)  AS credit_hour_low,
                          MAX(credit_hour_high) AS credit_hour_high,
                          COUNT(*)              AS section_count
                   FROM courses
                   WHERE term_code=%s AND subject=%s AND course_number=%s
                   GROUP BY subject, course_number""",
                (term["code"], subject.upper(), course_number),
            )
        if not row:
            return HTMLResponse(_404_html(), status_code=404)
        c = row_to_dict(row)
        label = f"{c['subject']} {c['course_number']}"
        title = f"{label}: {c['title'] or 'Untitled'}"
        desc = (
            c["description"][:200]
            if c["description"]
            else f"{label} at Northeastern University — {c['section_count']} section(s) offered"
        )
        return HTMLResponse(_spa_html(
            page_title=title,
            description=desc,
            canonical=canonical,
            active_view="detail",
            detail_html=_course_detail_html(c, term, label),
            json_ld={
                "@context": "https://schema.org",
                "@type": "Course",
                "name": c["title"] or label,
                "courseCode": label,
                "description": desc,
                "provider": {
                    "@type": "CollegeOrUniversity",
                    "name": "Northeastern University",
                    "sameAs": "https://www.northeastern.edu",
                },
            },
        ))
    except Exception:
        logger.exception("course_page failed for %s", canonical)
        return HTMLResponse(_error_html(), status_code=500)


def _course_detail_html(c: dict, term: dict, label: str) -> str:
    esc = _html.escape
    title = c["title"] or "Untitled"
    desc = c.get("description") or ""
    prereqs = c.get("prerequisites") or ""
    section_count = c.get("section_count") or 0
    cred_lo = c.get("credit_hour_low")
    cred_hi = c.get("credit_hour_high")
    if cred_lo is not None and cred_hi is not None:
        credits = (
            f"{cred_lo:g}" if cred_lo == cred_hi
            else f"{cred_lo:g}–{cred_hi:g}"
        )
        credit_html = f'<p class="course-credits"><strong>Credits:</strong> {esc(credits)}</p>'
    else:
        credit_html = ""
    desc_html = f'<p class="course-description">{esc(desc)}</p>' if desc else ""
    prereq_html = (
        f'<section class="course-prereqs"><h2>Prerequisites</h2><p>{esc(prereqs)}</p></section>'
        if prereqs else ""
    )
    return f"""
      <article class="course-detail-ssr">
        <header class="course-header">
          <p class="course-term">{esc(term["description"])}</p>
          <h1 class="course-title">{esc(label)}: {esc(title)}</h1>
          {credit_html}
          <p class="course-section-count">{section_count} section{"s" if section_count != 1 else ""} offered this term.</p>
        </header>
        {desc_html}
        {prereq_html}
      </article>
    """


@app.get("/api/terms", response_model=list[Term])
def list_terms():
    with get_db() as db:
        rows = fetchall(db, "SELECT code, description FROM terms ORDER BY code DESC")
    return [Term(**row_to_dict(r)) for r in rows]


@app.get("/api/terms/{term_code}/subjects", response_model=list[Subject])
def list_subjects(term_code: str):
    with get_db() as db:
        rows = fetchall(db,
            "SELECT code, description FROM subjects WHERE term_code=%s ORDER BY code",
            (term_code,))
    if not rows:
        raise HTTPException(404, "Term not found or has no subjects")
    return [Subject(**row_to_dict(r)) for r in rows]


@app.get("/api/terms/{term_code}/campuses", response_model=list[str])
def list_campuses(term_code: str):
    with get_db() as db:
        rows = fetchall(db,
            "SELECT DISTINCT campus FROM courses WHERE term_code=%s AND campus IS NOT NULL ORDER BY campus",
            (term_code,))
    return [r["campus"] for r in rows]


@app.get("/api/terms/{term_code}/courses", response_model=SearchResult)
def list_courses(
    term_code: str,
    subject: Optional[str] = None,
    campus: Optional[str] = None,
    q: Optional[str] = Query(None, description="Full-text search query"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    subject_filter = "AND subject = %s" if subject else ""
    subject_param = [subject] if subject else []
    campus_filter = "AND campus = %s" if campus else ""
    campus_param = [campus] if campus else []

    _rank_order = """
            CASE WHEN LOWER(MAX(title)) = LOWER(%s) THEN 0 ELSE 1 END,
            ts_rank_cd(
                setweight(to_tsvector('english', coalesce(MAX(title),'')),       'A') ||
                setweight(to_tsvector('english', coalesce(subject,'')),           'B') ||
                setweight(to_tsvector('english', coalesce(MAX(description),'')), 'C'),
                websearch_to_tsquery('english', %s)
            ) DESC,
            subject, CAST(course_number AS INTEGER)"""

    _base_fts = """to_tsvector('english',
            coalesce(subject,'') || ' ' ||
            coalesce(course_number,'') || ' ' ||
            coalesce(title,'') || ' ' ||
            coalesce(description,'')
        ) @@ websearch_to_tsquery('english', %s)"""

    if q:
        m = _COURSE_CODE_RE.match(q)
        if m:
            # "CS 1800" — guarantee the exact course appears even if FTS misses it,
            # and pin it to position 0 in the ranking.
            parsed_subj = m.group(1).upper()
            parsed_num  = m.group(2)
            fts_condition = f"""AND (
                (UPPER(subject) = %s AND course_number = %s)
                OR {_base_fts}
            )"""
            fts_params = [parsed_subj, parsed_num, q]
            order_clause = f"""ORDER BY
            CASE WHEN UPPER(subject) = %s AND course_number = %s THEN 0 ELSE 1 END,
            {_rank_order}"""
            order_params = [parsed_subj, parsed_num, q, q]
        else:
            fts_condition = f"AND {_base_fts}"
            fts_params = [q]
            order_clause = f"ORDER BY {_rank_order}"
            order_params = [q, q]
    else:
        fts_condition = ""
        fts_params = []
        order_clause = "ORDER BY subject, CAST(course_number AS INTEGER)"
        order_params = []

    with get_db() as db:
        total_row = fetchone(db,
            f"""SELECT COUNT(DISTINCT subject || '|' || course_number) AS cnt
                FROM courses
                WHERE term_code = %s {subject_filter} {campus_filter} {fts_condition}""",
            [term_code] + subject_param + campus_param + fts_params,
        )
        total = total_row["cnt"]

        if total == 0:
            return SearchResult(total=0, offset=offset, limit=limit, results=[])

        rows = fetchall(db,
            f"""SELECT
                    subject, subject_description, course_number,
                    MAX(course_title)     AS course_title,
                    MAX(title)            AS title,
                    MAX(credit_hour_low)  AS credit_hour_low,
                    MAX(credit_hour_high) AS credit_hour_high,
                    MAX(description)      AS description,
                    MAX(prerequisites)    AS prerequisites,
                    COUNT(*)              AS section_count
                FROM courses
                WHERE term_code = %s {subject_filter} {campus_filter} {fts_condition}
                GROUP BY subject, subject_description, course_number
                {order_clause}
                LIMIT %s OFFSET %s""",
            [term_code] + subject_param + campus_param + fts_params + order_params + [limit, offset],
        )

    return SearchResult(
        total=total, offset=offset, limit=limit,
        results=[CourseGroup(**row_to_dict(r)) for r in rows],
    )


def _build_sections(db, rows) -> list[CourseSection]:
    sections = []
    for row in rows:
        crn = row["crn"]
        term_code = row["term_code"]
        meetings = fetchall(db,
            "SELECT * FROM meetings WHERE crn=%s AND term_code=%s", (crn, term_code))
        fac = fetchall(db,
            "SELECT * FROM faculty WHERE crn=%s AND term_code=%s", (crn, term_code))
        attrs = fetchall(db,
            "SELECT * FROM section_attributes WHERE crn=%s AND term_code=%s", (crn, term_code))
        d = row_to_dict(row)
        sections.append(CourseSection(
            **d,
            meetings=[MeetingTime(**row_to_dict(m)) for m in meetings],
            faculty=[FacultyMember(**row_to_dict(f)) for f in fac],
            attributes=[SectionAttribute(**row_to_dict(a)) for a in attrs],
        ))
    return sections


@app.get("/api/terms/{term_code}/courses/{subject}/{course_number}/sections",
         response_model=list[CourseSection])
def get_sections(term_code: str, subject: str, course_number: str):
    with get_db() as db:
        rows = fetchall(db,
            "SELECT * FROM courses WHERE term_code=%s AND subject=%s AND course_number=%s ORDER BY crn",
            (term_code, subject.upper(), course_number))
        if not rows:
            raise HTTPException(404, "Course not found")
        return _build_sections(db, rows)


@app.get("/api/terms/{term_code}/courses/{subject}/{course_number}",
         response_model=CourseGroup)
def get_course(term_code: str, subject: str, course_number: str):
    with get_db() as db:
        row = fetchone(db,
            """SELECT subject, subject_description, course_number,
                      MAX(course_title)     AS course_title,
                      MAX(course_title)     AS title,
                      MAX(credit_hour_low)  AS credit_hour_low,
                      MAX(credit_hour_high) AS credit_hour_high,
                      MAX(description)      AS description,
                      MAX(prerequisites)    AS prerequisites,
                      COUNT(*)              AS section_count
               FROM courses
               WHERE term_code=%s AND subject=%s AND course_number=%s
               GROUP BY subject, subject_description, course_number""",
            (term_code, subject.upper(), course_number))
    if not row:
        raise HTTPException(404, "Course not found")
    return CourseGroup(**row_to_dict(row))


@app.get("/api/terms/{term_code}/instructors", response_model=list[InstructorSummary])
def search_instructors(term_code: str, q: str = Query(..., min_length=1)):
    tokens = q.strip().split()
    conditions = " AND ".join("LOWER(name) LIKE %s" for _ in tokens)
    params = [term_code] + [f"%{t.lower()}%" for t in tokens]
    with get_db() as db:
        rows = fetchall(db,
            f"""SELECT name, email, COUNT(DISTINCT crn) AS section_count
                FROM faculty
                WHERE term_code=%s AND {conditions}
                GROUP BY name, email
                ORDER BY name
                LIMIT 20""",
            params)
    return [InstructorSummary(**row_to_dict(r)) for r in rows]


@app.get("/api/terms/{term_code}/instructors/{instructor_name}/sections",
         response_model=list[CourseSection])
def get_instructor_sections(term_code: str, instructor_name: str):
    tokens = instructor_name.strip().split()
    conditions = " AND ".join("LOWER(name) LIKE %s" for _ in tokens)
    params = [term_code] + [f"%{t.lower()}%" for t in tokens]
    with get_db() as db:
        crns = [r["crn"] for r in fetchall(db,
            f"SELECT DISTINCT crn FROM faculty WHERE term_code=%s AND {conditions}",
            params)]
        if not crns:
            raise HTTPException(404, "Instructor not found")
        placeholders = ",".join(["%s"] * len(crns))
        rows = fetchall(db,
            f"""SELECT * FROM courses WHERE term_code=%s AND crn IN ({placeholders})
                ORDER BY subject, CAST(course_number AS INTEGER), crn""",
            [term_code] + crns)
        return _build_sections(db, rows)



def _latest_term(db) -> dict | None:
    rows = fetchall(db, "SELECT code, description FROM terms ORDER BY code DESC LIMIT 1")
    return rows[0] if rows else None


@app.get("/subjects", response_class=HTMLResponse)
def subjects_directory():
    canonical = f"{SITE_URL}/subjects"
    try:
        with get_db() as db:
            term = _latest_term(db)
            if not term:
                return HTMLResponse(_404_html(), status_code=404)
            subjects = fetchall(db,
                "SELECT code, description FROM subjects WHERE term_code=%s ORDER BY code",
                (term["code"],))
        if not subjects:
            return HTMLResponse(_404_html(), status_code=404)
        esc = _html.escape
        items = "\n".join(
            f'<li><a href="/subject/{esc(s["code"])}">{esc(s["code"])} — {esc(s["description"] or "")}</a></li>'
            for s in subjects
        )
        body = f'<ul class="subject-directory">{items}</ul>'
        return HTMLResponse(_directory_html(
            page_title="Browse Subjects",
            description=f"Browse all {len(subjects)} academic subjects offered at Northeastern University, from Computer Science to Biology to Accounting.",
            canonical=canonical,
            h1="Browse all subjects",
            intro_html=f'<p class="directory-intro">All subjects with courses offered in {esc(term["description"])}. Click a subject to see its courses.</p>',
            body_html=body,
        ))
    except Exception:
        logger.exception("subjects_directory failed")
        return HTMLResponse(_error_html(), status_code=500)


@app.get("/subject/{subject}", response_class=HTMLResponse)
def subject_directory(subject: str):
    subject_upper = subject.upper()
    if subject != subject_upper:
        return RedirectResponse(f"/subject/{subject_upper}", status_code=301)
    canonical = f"{SITE_URL}/subject/{subject_upper}"
    try:
        with get_db() as db:
            term = _latest_term(db)
            if not term:
                return HTMLResponse(_404_html(), status_code=404)
            term_path = _term_desc_to_path(term["description"])
            subj_row = fetchone(db,
                "SELECT description FROM subjects WHERE term_code=%s AND code=%s",
                (term["code"], subject_upper))
            if not subj_row:
                return HTMLResponse(_404_html(), status_code=404)
            courses = fetchall(db,
                """SELECT subject, course_number,
                          MAX(course_title) AS title,
                          COUNT(*)          AS section_count
                   FROM courses
                   WHERE term_code=%s AND subject=%s
                   GROUP BY subject, course_number
                   ORDER BY CAST(course_number AS INTEGER)""",
                (term["code"], subject_upper))
        if not courses:
            return HTMLResponse(_404_html(), status_code=404)
        esc = _html.escape
        subj_desc = subj_row["description"] or subject_upper
        items = "\n".join(
            f'<li><a href="/schedule/{term_path}/{esc(c["subject"])}/{esc(c["course_number"])}">'
            f'{esc(c["subject"])} {esc(c["course_number"])} — {esc(c["title"] or "Untitled")}</a> '
            f'<span class="section-count">({c["section_count"]} section{"s" if c["section_count"] != 1 else ""})</span></li>'
            for c in courses
        )
        body = f'<ul class="course-directory">{items}</ul>'
        return HTMLResponse(_directory_html(
            page_title=f"{subj_desc} courses",
            description=f"Browse all {len(courses)} {subj_desc} ({subject_upper}) courses offered at Northeastern University in {term['description']}.",
            canonical=canonical,
            h1=f"{subj_desc} ({subject_upper})",
            intro_html=f'<p class="directory-intro">All {subject_upper} courses offered in {esc(term["description"])}. <a href="/subjects">Browse other subjects</a>.</p>',
            body_html=body,
        ))
    except Exception:
        logger.exception("subject_directory failed for %s", subject)
        return HTMLResponse(_error_html(), status_code=500)


@app.head("/sitemap.xml", include_in_schema=False)
def sitemap_head():
    return Response(media_type="text/xml; charset=utf-8")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    with get_db() as db:
        terms = fetchall(db, "SELECT code, description FROM terms ORDER BY code DESC LIMIT 2")

        urls = [f"""  <url>
    <loc>{SITE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>""", f"""  <url>
    <loc>{SITE_URL}/subjects</loc>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>"""]

        if terms:
            latest_subjects = fetchall(db,
                "SELECT code FROM subjects WHERE term_code=%s ORDER BY code",
                (terms[0]["code"],))
            for s in latest_subjects:
                urls.append(f"""  <url>
    <loc>{SITE_URL}/subject/{s["code"]}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

        for term in terms:
            term_path = _term_desc_to_path(term["description"])
            if not term_path:
                continue
            courses = fetchall(db,
                """SELECT DISTINCT subject, course_number
                   FROM courses WHERE term_code=%s
                   ORDER BY subject, course_number""",
                (term["code"],))
            for c in courses:
                url = f"{SITE_URL}/schedule/{term_path}/{c['subject']}/{c['course_number']}"
                urls.append(f"""  <url>
    <loc>{url}</loc>
    <priority>0.7</priority>
  </url>""")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xsi:schemaLocation="http://www.sitemaps.org/schemas/sitemap/0.9 http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>"
    return Response(content=xml, media_type="text/xml; charset=utf-8")


@app.get("/api/health")
def health():
    with get_db() as db:
        row = fetchone(db,
            """SELECT
                (SELECT COUNT(*) FROM terms)   AS terms,
                (SELECT COUNT(*) FROM courses) AS courses""")
    return {"status": "ok", "terms": row["terms"], "courses": row["courses"]}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return HTMLResponse(_404_html(), status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ── Serve static frontend (local dev only) ────────────────────────────────
WEB_DIR = os.environ.get("WEB_DIR", "")
if WEB_DIR and os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")
