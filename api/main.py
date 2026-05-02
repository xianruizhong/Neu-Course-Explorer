"""
NEU Course Explorer — FastAPI backend
Serves course data from the SQLite database created by the scraper.
"""

import sqlite3
import os
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

DB_PATH = os.environ.get("DB_PATH", "../scraper/courses.db")

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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
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
    meetings: list[MeetingTime] = []
    faculty: list[FacultyMember] = []
    attributes: list[SectionAttribute] = []


class CourseGroup(BaseModel):
    subject: str
    subject_description: Optional[str]
    course_number: str
    title: Optional[str]
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
        rows = db.execute("SELECT code, description FROM terms ORDER BY code DESC").fetchall()
    return [Term(**row_to_dict(r)) for r in rows]


@app.get("/api/terms/{term_code}/subjects", response_model=list[Subject])
def list_subjects(term_code: str):
    with get_db() as db:
        rows = db.execute(
            "SELECT code, description FROM subjects WHERE term_code=? ORDER BY description",
            (term_code,)
        ).fetchall()
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
    """
    List courses grouped by (subject, course_number).
    Supports filtering by subject and full-text search.
    """
    with get_db() as db:
        # Build base query — group sections into course-level rows
        if q:
            # FTS search: get matching CRNs first
            fts_rows = db.execute(
                """
                SELECT crn, term_code FROM courses_fts
                WHERE courses_fts MATCH ? AND term_code = ?
                """,
                (q, term_code),
            ).fetchall()
            crns = tuple(r["crn"] for r in fts_rows)
            if not crns:
                return SearchResult(total=0, offset=offset, limit=limit, results=[])

            crn_filter = f"AND crn IN ({','.join('?' * len(crns))})"
            base_params = list(crns)
        else:
            crn_filter = ""
            base_params = []

        subject_filter = "AND subject = ?" if subject else ""
        subject_param = [subject] if subject else []

        count_sql = f"""
            SELECT COUNT(DISTINCT subject || '|' || course_number) as cnt
            FROM courses
            WHERE term_code = ?
            {subject_filter}
            {crn_filter}
        """
        total = db.execute(
            count_sql, [term_code] + subject_param + base_params
        ).fetchone()["cnt"]

        # Aggregate sections into course-level rows
        sql = f"""
            SELECT
                subject, subject_description, course_number, title,
                MAX(credit_hour_low) as credit_hour_low,
                MAX(credit_hour_high) as credit_hour_high,
                MAX(description) as description,
                MAX(prerequisites) as prerequisites,
                COUNT(*) as section_count
            FROM courses
            WHERE term_code = ?
            {subject_filter}
            {crn_filter}
            GROUP BY subject, course_number
            ORDER BY subject, CAST(course_number AS INTEGER)
            LIMIT ? OFFSET ?
        """
        rows = db.execute(
            sql, [term_code] + subject_param + base_params + [limit, offset]
        ).fetchall()

    results = [
        CourseGroup(
            subject=r["subject"],
            subject_description=r["subject_description"],
            course_number=r["course_number"],
            title=r["title"],
            credit_hour_low=r["credit_hour_low"],
            credit_hour_high=r["credit_hour_high"],
            description=r["description"],
            prerequisites=r["prerequisites"],
            section_count=r["section_count"],
        )
        for r in rows
    ]
    return SearchResult(total=total, offset=offset, limit=limit, results=results)


def _build_sections(db: sqlite3.Connection, rows, term_code: str) -> list[CourseSection]:
    sections = []
    for row in rows:
        crn = row["crn"]
        meetings = db.execute(
            "SELECT * FROM meetings WHERE crn=? AND term_code=?", (crn, term_code)
        ).fetchall()
        fac = db.execute(
            "SELECT * FROM faculty WHERE crn=? AND term_code=?", (crn, term_code)
        ).fetchall()
        attrs = db.execute(
            "SELECT * FROM section_attributes WHERE crn=? AND term_code=?", (crn, term_code)
        ).fetchall()
        d = row_to_dict(row)
        d["open_section"] = bool(d.get("open_section"))
        sections.append(CourseSection(
            **d,
            meetings=[
                MeetingTime(
                    begin_time=m["begin_time"], end_time=m["end_time"],
                    start_date=m["start_date"], end_date=m["end_date"],
                    building=m["building"], building_desc=m["building_desc"],
                    room=m["room"],
                    monday=bool(m["monday"]), tuesday=bool(m["tuesday"]),
                    wednesday=bool(m["wednesday"]), thursday=bool(m["thursday"]),
                    friday=bool(m["friday"]), saturday=bool(m["saturday"]),
                    sunday=bool(m["sunday"]),
                    schedule_type=m["schedule_type"],
                )
                for m in meetings
            ],
            faculty=[
                FacultyMember(name=f["name"], email=f["email"], primary_ind=bool(f["primary_ind"]))
                for f in fac
            ],
            attributes=[
                SectionAttribute(code=a["code"], description=a["description"])
                for a in attrs
            ],
        ))
    return sections


@app.get("/api/terms/{term_code}/courses/{subject}/{course_number}/sections",
         response_model=list[CourseSection])
def get_sections(term_code: str, subject: str, course_number: str):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM courses WHERE term_code=? AND subject=? AND course_number=? ORDER BY crn",
            (term_code, subject.upper(), course_number),
        ).fetchall()
        if not rows:
            raise HTTPException(404, "Course not found")
        return _build_sections(db, rows, term_code)


@app.get("/api/terms/{term_code}/instructors", response_model=list[InstructorSummary])
def search_instructors(term_code: str, q: str = Query(..., min_length=1)):
    tokens = q.strip().split()
    token_conditions = " AND ".join("LOWER(name) LIKE ?" for _ in tokens)
    token_params = [f"%{t.lower()}%" for t in tokens]
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT name, email, COUNT(DISTINCT crn) as section_count
            FROM faculty
            WHERE term_code=? AND {token_conditions}
            GROUP BY name
            ORDER BY name
            LIMIT 20
            """,
            [term_code] + token_params,
        ).fetchall()
    return [InstructorSummary(name=r["name"], email=r["email"], section_count=r["section_count"]) for r in rows]


@app.get("/api/terms/{term_code}/instructors/{instructor_name}/sections",
         response_model=list[CourseSection])
def get_instructor_sections(term_code: str, instructor_name: str):
    tokens = instructor_name.strip().split()
    token_conditions = " AND ".join("LOWER(name) LIKE ?" for _ in tokens)
    token_params = [f"%{t.lower()}%" for t in tokens]
    with get_db() as db:
        crns = [r["crn"] for r in db.execute(
            f"SELECT DISTINCT crn FROM faculty WHERE term_code=? AND {token_conditions}",
            [term_code] + token_params,
        ).fetchall()]
        if not crns:
            raise HTTPException(404, "Instructor not found")
        placeholders = ",".join("?" * len(crns))
        rows = db.execute(
            f"SELECT * FROM courses WHERE term_code=? AND crn IN ({placeholders})"
            " ORDER BY subject, CAST(course_number AS INTEGER), crn",
            [term_code] + crns,
        ).fetchall()
        return _build_sections(db, rows, term_code)


@app.get("/api/terms/{term_code}/courses/{subject}/{course_number}",
         response_model=CourseGroup)
def get_course(term_code: str, subject: str, course_number: str):
    """Get course-level info (aggregated from all sections)."""
    with get_db() as db:
        row = db.execute(
            """
            SELECT subject, subject_description, course_number, title,
                   MAX(credit_hour_low) as credit_hour_low,
                   MAX(credit_hour_high) as credit_hour_high,
                   MAX(description) as description,
                   MAX(prerequisites) as prerequisites,
                   COUNT(*) as section_count
            FROM courses
            WHERE term_code=? AND subject=? AND course_number=?
            GROUP BY subject, course_number
            """,
            (term_code, subject.upper(), course_number),
        ).fetchone()

    if not row:
        raise HTTPException(404, "Course not found")

    return CourseGroup(**row_to_dict(row))


@app.get("/api/health")
def health():
    with get_db() as db:
        counts = db.execute(
            "SELECT (SELECT COUNT(*) FROM terms) as terms, "
            "(SELECT COUNT(*) FROM courses) as courses"
        ).fetchone()
    return {"status": "ok", "terms": counts["terms"], "courses": counts["courses"]}


# ── Serve static frontend ──────────────────────────────────────────────────
WEB_DIR = os.environ.get("WEB_DIR", "../web")
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")
