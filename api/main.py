"""
NEU Course Explorer — FastAPI backend
Serves course data from PostgreSQL (connection string via DATABASE_URL).
"""

import os
import re
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL", "")

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
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/terms", response_model=list[Term])
def list_terms():
    with get_db() as db:
        rows = fetchall(db, "SELECT code, description FROM terms ORDER BY code DESC")
    return [Term(**row_to_dict(r)) for r in rows]


@app.get("/api/terms/{term_code}/subjects", response_model=list[Subject])
def list_subjects(term_code: str):
    with get_db() as db:
        rows = fetchall(db,
            "SELECT code, description FROM subjects WHERE term_code=%s ORDER BY description",
            (term_code,))
    if not rows:
        raise HTTPException(404, "Term not found or has no subjects")
    return [Subject(**row_to_dict(r)) for r in rows]


@app.get("/api/terms/{term_code}/courses", response_model=SearchResult)
def list_courses(
    term_code: str,
    subject: Optional[str] = None,
    q: Optional[str] = Query(None, description="Full-text search query"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    subject_filter = "AND subject = %s" if subject else ""
    subject_param = [subject] if subject else []

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
                WHERE term_code = %s {subject_filter} {fts_condition}""",
            [term_code] + subject_param + fts_params,
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
                WHERE term_code = %s {subject_filter} {fts_condition}
                GROUP BY subject, subject_description, course_number
                {order_clause}
                LIMIT %s OFFSET %s""",
            [term_code] + subject_param + fts_params + order_params + [limit, offset],
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


SITE_URL = "https://neu-course-explorer.vercel.app"

@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    with get_db() as db:
        terms = fetchall(db, "SELECT code FROM terms ORDER BY code DESC LIMIT 2")
        term_codes = [r["code"] for r in terms]

        urls = [f"""  <url>
    <loc>{SITE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>"""]

        for code in term_codes:
            courses = fetchall(db,
                """SELECT DISTINCT subject, course_number
                   FROM courses WHERE term_code=%s
                   ORDER BY subject, course_number""",
                (code,))
            for c in courses:
                frag = f"view=detail&term={code}&subject={c['subject']}&number={c['course_number']}"
                urls.append(f"""  <url>
    <loc>{SITE_URL}/#{frag}</loc>
    <priority>0.7</priority>
  </url>""")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>"
    return Response(content=xml, media_type="application/xml")


@app.get("/api/health")
def health():
    with get_db() as db:
        row = fetchone(db,
            """SELECT
                (SELECT COUNT(*) FROM terms)   AS terms,
                (SELECT COUNT(*) FROM courses) AS courses""")
    return {"status": "ok", "terms": row["terms"], "courses": row["courses"]}


# ── Serve static frontend (local dev only) ────────────────────────────────
WEB_DIR = os.environ.get("WEB_DIR", "")
if WEB_DIR and os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")
