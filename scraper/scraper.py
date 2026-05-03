"""
NEU Banner Course Scraper
Fetches course data from nubanner.neu.edu (no login required).
Stores everything in a PostgreSQL database (connection string via DATABASE_URL).
"""

import os
from dotenv import load_dotenv
load_dotenv()
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import psycopg2
import psycopg2.extras
import time
import re
import logging
import argparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

BASE_URL = "https://nubanner.neu.edu/StudentRegistrationSsb/ssb"
PAGE_SIZE = 500
MAX_WORKERS = 4       # concurrent detail fetches
ENROLLMENT_WORKERS = 10  # concurrent subject fetches for enrollment refresh
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS terms (
        code        TEXT PRIMARY KEY,
        description TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS subjects (
        code        TEXT NOT NULL,
        description TEXT NOT NULL,
        term_code   TEXT NOT NULL REFERENCES terms(code) ON DELETE CASCADE,
        PRIMARY KEY (code, term_code)
    )""",
    """CREATE TABLE IF NOT EXISTS courses (
        crn                 TEXT NOT NULL,
        term_code           TEXT NOT NULL REFERENCES terms(code) ON DELETE CASCADE,
        subject             TEXT NOT NULL,
        subject_description TEXT,
        course_number       TEXT NOT NULL,
        title               TEXT,
        credit_hour_low     DOUBLE PRECISION,
        credit_hour_high    DOUBLE PRECISION,
        campus              TEXT,
        schedule_type       TEXT,
        part_of_term        TEXT,
        enrollment          INTEGER,
        max_enrollment      INTEGER,
        seats_available     INTEGER,
        wait_count          INTEGER,
        wait_capacity       INTEGER,
        wait_available      INTEGER,
        open_section        BOOLEAN DEFAULT FALSE,
        description         TEXT,
        prerequisites       TEXT,
        scraped_at          TEXT,
        sequence_number     TEXT,
        course_title        TEXT,
        PRIMARY KEY (crn, term_code)
    )""",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS sequence_number TEXT",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_title TEXT",
    """CREATE TABLE IF NOT EXISTS meetings (
        id            SERIAL PRIMARY KEY,
        crn           TEXT NOT NULL,
        term_code     TEXT NOT NULL,
        begin_time    TEXT,
        end_time      TEXT,
        start_date    TEXT,
        end_date      TEXT,
        building      TEXT,
        building_desc TEXT,
        room          TEXT,
        monday        BOOLEAN DEFAULT FALSE,
        tuesday       BOOLEAN DEFAULT FALSE,
        wednesday     BOOLEAN DEFAULT FALSE,
        thursday      BOOLEAN DEFAULT FALSE,
        friday        BOOLEAN DEFAULT FALSE,
        saturday      BOOLEAN DEFAULT FALSE,
        sunday        BOOLEAN DEFAULT FALSE,
        schedule_type TEXT,
        FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS faculty (
        id          SERIAL PRIMARY KEY,
        crn         TEXT NOT NULL,
        term_code   TEXT NOT NULL,
        banner_id   TEXT,
        name        TEXT,
        email       TEXT,
        primary_ind BOOLEAN DEFAULT FALSE,
        FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS section_attributes (
        id          SERIAL PRIMARY KEY,
        crn         TEXT NOT NULL,
        term_code   TEXT NOT NULL,
        code        TEXT,
        description TEXT,
        FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_courses_term    ON courses(term_code)",
    "CREATE INDEX IF NOT EXISTS idx_courses_subject ON courses(subject, term_code)",
    "CREATE INDEX IF NOT EXISTS idx_courses_number  ON courses(course_number)",
    """CREATE INDEX IF NOT EXISTS idx_courses_fts ON courses
        USING GIN(to_tsvector('english',
            coalesce(subject, '') || ' ' ||
            coalesce(course_number, '') || ' ' ||
            coalesce(title, '') || ' ' ||
            coalesce(description, '')
        ))""",
]


def init_db(dsn: str):
    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        for stmt in _SCHEMA:
            cur.execute(stmt)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Banner API helpers
# ---------------------------------------------------------------------------

def make_session(term_code: str) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        backoff_factor=1,          # waits 1s, 2s, 4s, 8s, 16s between attempts
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "NEU-Course-Explorer/1.0",
        "Accept": "application/json",
    })
    resp = session.post(
        f"{BASE_URL}/term/search",
        params={"mode": "courseSearch"},
        data={"term": term_code},
        timeout=15,
    )
    resp.raise_for_status()
    return session


def get_all_terms(session: requests.Session) -> list[dict]:
    terms = []
    offset = 1
    while True:
        resp = session.get(
            f"{BASE_URL}/classSearch/getTerms",
            params={"offset": offset, "max": 100},
            timeout=15,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        terms.extend(batch)
        if len(batch) < 100:
            break
        offset += 1
    return terms


def get_all_subjects(session: requests.Session, term_code: str) -> list[dict]:
    subjects = []
    offset = 1
    while True:
        resp = session.get(
            f"{BASE_URL}/classSearch/get_subject",
            params={"term": term_code, "offset": offset, "max": 100},
            timeout=15,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        subjects.extend(batch)
        if len(batch) < 100:
            break
        offset += 1
    return subjects


def search_courses(session: requests.Session, term_code: str, subject: str) -> list[dict]:
    all_sections = []
    offset = 0
    while True:
        resp = session.get(
            f"{BASE_URL}/searchResults/searchResults",
            params={
                "txt_subject": subject,
                "txt_term": term_code,
                "pageOffset": offset,
                "pageMaxSize": PAGE_SIZE,
                "sortColumn": "subjectDescription",
                "sortDirection": "asc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success") or not data.get("data"):
            break
        all_sections.extend(data["data"])
        if offset + PAGE_SIZE >= data["totalCount"]:
            break
        offset += PAGE_SIZE
    return all_sections


def get_catalog_titles(session: requests.Session, subject: str, term_code: str) -> dict[str, str]:
    """Returns {courseNumber: catalogTitle} from the course catalog endpoint."""
    try:
        offset = 0
        titles = {}
        while True:
            resp = session.get(
                f"{BASE_URL}/courseSearchResults/courseSearchResults",
                params={
                    "txt_subject": subject,
                    "txt_term": term_code,
                    "pageOffset": offset,
                    "pageMaxSize": PAGE_SIZE,
                    "sortColumn": "subjectDescription",
                    "sortDirection": "asc",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("data") or []:
                titles[item["courseNumber"]] = item["courseTitle"]
            if offset + PAGE_SIZE >= data.get("totalCount", 0):
                break
            offset += PAGE_SIZE
        return titles
    except Exception as e:
        log.warning(f"Catalog title fetch failed for {subject}: {e}")
        return {}


def _post_with_retry(session: requests.Session, url: str, data: dict) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, data=data, timeout=20)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                raise e
    return ""


def get_course_description(session: requests.Session, crn: str, term_code: str) -> str:
    try:
        html = _post_with_retry(session,
            f"{BASE_URL}/searchResults/getCourseDescription",
            {"term": term_code, "courseReferenceNumber": crn},
        )
        soup = BeautifulSoup(html, "html.parser")
        section = soup.find("section")
        if not section:
            return ""
        return re.sub(r"\s+", " ", section.get_text(separator=" ", strip=True)).strip()
    except Exception as e:
        log.warning(f"Description fetch failed for CRN {crn}: {e}")
        return ""


def get_prerequisites(session: requests.Session, crn: str, term_code: str) -> str:
    try:
        html = _post_with_retry(session,
            f"{BASE_URL}/searchResults/getSectionPrerequisites",
            {"term": term_code, "courseReferenceNumber": crn},
        )
        soup = BeautifulSoup(html, "html.parser")
        section = soup.find("section")
        if not section:
            return ""
        text = re.sub(r"\s+", " ", section.get_text(separator=" ", strip=True)).strip()
        if "No prerequisite information available" in text:
            return ""
        return re.sub(r"^Catalog Prerequisites\s*", "", text).strip()
    except Exception as e:
        log.warning(f"Prereq fetch failed for CRN {crn}: {e}")
        return ""


def get_faculty_meeting_times(session: requests.Session, crn: str, term_code: str) -> list[dict]:
    try:
        resp = session.get(
            f"{BASE_URL}/searchResults/getFacultyMeetingTimes",
            params={"term": term_code, "courseReferenceNumber": crn},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("fmt", [])
    except Exception as e:
        log.warning(f"Faculty/meeting fetch failed for CRN {crn}: {e}")
        return []


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------

def upsert_section(conn, section: dict, term_code: str,
                   description: str, prerequisites: str, fmt: list[dict],
                   course_title: str = ""):
    crn = section["courseReferenceNumber"]
    now = datetime.utcnow().isoformat()

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO courses (
                crn, term_code, subject, subject_description, course_number, title,
                credit_hour_low, credit_hour_high, campus, schedule_type, part_of_term,
                enrollment, max_enrollment, seats_available,
                wait_count, wait_capacity, wait_available, open_section,
                description, prerequisites, scraped_at, sequence_number, course_title
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (crn, term_code) DO UPDATE SET
                subject             = EXCLUDED.subject,
                subject_description = EXCLUDED.subject_description,
                course_number       = EXCLUDED.course_number,
                title               = EXCLUDED.title,
                credit_hour_low     = EXCLUDED.credit_hour_low,
                credit_hour_high    = EXCLUDED.credit_hour_high,
                campus              = EXCLUDED.campus,
                schedule_type       = EXCLUDED.schedule_type,
                part_of_term        = EXCLUDED.part_of_term,
                enrollment          = EXCLUDED.enrollment,
                max_enrollment      = EXCLUDED.max_enrollment,
                seats_available     = EXCLUDED.seats_available,
                wait_count          = EXCLUDED.wait_count,
                wait_capacity       = EXCLUDED.wait_capacity,
                wait_available      = EXCLUDED.wait_available,
                open_section        = EXCLUDED.open_section,
                description         = EXCLUDED.description,
                prerequisites       = EXCLUDED.prerequisites,
                scraped_at          = EXCLUDED.scraped_at,
                sequence_number     = EXCLUDED.sequence_number,
                course_title        = EXCLUDED.course_title
        """, (
            crn, term_code,
            section.get("subject"), section.get("subjectDescription"),
            section.get("courseNumber"), section.get("courseTitle"),
            section.get("creditHourLow"), section.get("creditHourHigh"),
            section.get("campusDescription"), section.get("scheduleTypeDescription"),
            section.get("partOfTerm"),
            section.get("enrollment"), section.get("maximumEnrollment"),
            section.get("seatsAvailable"),
            section.get("waitCount"), section.get("waitCapacity"),
            section.get("waitAvailable"),
            bool(section.get("openSection")),
            description, prerequisites, now,
            section.get("sequenceNumber"),
            course_title or section.get("courseTitle"),
        ))

        cur.execute("DELETE FROM meetings WHERE crn=%s AND term_code=%s", (crn, term_code))
        cur.execute("DELETE FROM faculty WHERE crn=%s AND term_code=%s", (crn, term_code))
        cur.execute("DELETE FROM section_attributes WHERE crn=%s AND term_code=%s", (crn, term_code))

        seen_faculty = set()
        for mf in fmt:
            mt = mf.get("meetingTime", {})
            cur.execute("""
                INSERT INTO meetings
                (crn, term_code, begin_time, end_time, start_date, end_date,
                 building, building_desc, room,
                 monday, tuesday, wednesday, thursday, friday, saturday, sunday,
                 schedule_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                crn, term_code,
                mt.get("beginTime"), mt.get("endTime"),
                mt.get("startDate"), mt.get("endDate"),
                mt.get("building"), mt.get("buildingDescription"), mt.get("room"),
                bool(mt.get("monday")), bool(mt.get("tuesday")),
                bool(mt.get("wednesday")), bool(mt.get("thursday")),
                bool(mt.get("friday")), bool(mt.get("saturday")),
                bool(mt.get("sunday")),
                mt.get("meetingScheduleType"),
            ))
            for f in mf.get("faculty", []):
                bid = f.get("bannerId")
                if bid in seen_faculty:
                    continue
                seen_faculty.add(bid)
                cur.execute("""
                    INSERT INTO faculty (crn, term_code, banner_id, name, email, primary_ind)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (
                    crn, term_code,
                    bid, f.get("displayName"), f.get("emailAddress"),
                    bool(f.get("primaryIndicator")),
                ))

        for attr in section.get("sectionAttributes", []):
            cur.execute("""
                INSERT INTO section_attributes (crn, term_code, code, description)
                VALUES (%s,%s,%s,%s)
            """, (crn, term_code, attr.get("code"), attr.get("description")))


def update_enrollment(conn, section: dict, term_code: str):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE courses SET
                enrollment=%s, max_enrollment=%s, seats_available=%s,
                wait_count=%s, wait_capacity=%s, wait_available=%s,
                open_section=%s, scraped_at=%s
            WHERE crn=%s AND term_code=%s
        """, (
            section.get("enrollment"), section.get("maximumEnrollment"),
            section.get("seatsAvailable"),
            section.get("waitCount"), section.get("waitCapacity"),
            section.get("waitAvailable"),
            bool(section.get("openSection")),
            datetime.utcnow().isoformat(),
            section["courseReferenceNumber"], term_code,
        ))


def fetch_details_batch(sections: list[dict], term_code: str, session: requests.Session):
    results = {}

    def fetch_one(section):
        crn = section["courseReferenceNumber"]
        desc = get_course_description(session, crn, term_code)
        prereqs = get_prerequisites(session, crn, term_code)
        fmt = get_faculty_meeting_times(session, crn, term_code)
        return crn, desc, prereqs, fmt

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_one, s): s for s in sections}
        for future in as_completed(futures):
            crn, desc, prereqs, fmt = future.result()
            results[crn] = (desc, prereqs, fmt)

    return results


def scrape_term(conn, term_code: str, term_desc: str,
                subjects_filter: list[str] | None = None):
    log.info(f"Scraping term: {term_desc} ({term_code})")

    list_session = make_session(term_code)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO terms (code, description) VALUES (%s, %s)
            ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
        """, (term_code, term_desc))
    conn.commit()

    subjects = get_all_subjects(list_session, term_code)
    log.info(f"  Found {len(subjects)} subjects")

    for subj in subjects:
        code = subj["code"]
        if subjects_filter and code not in subjects_filter:
            continue

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO subjects (code, description, term_code) VALUES (%s, %s, %s)
                ON CONFLICT (code, term_code) DO UPDATE SET description = EXCLUDED.description
            """, (code, subj["description"], term_code))

        log.info(f"  Fetching subject {code} ...")
        session = make_session(term_code)
        sections = search_courses(session, term_code, code)
        log.info(f"    {len(sections)} sections found")

        if not sections:
            conn.commit()
            continue

        catalog_titles = get_catalog_titles(session, code, term_code)
        details = fetch_details_batch(sections, term_code, session)

        for section in sections:
            crn = section["courseReferenceNumber"]
            desc, prereqs, fmt = details.get(crn, ("", "", []))
            course_title = catalog_titles.get(section.get("courseNumber", ""), "")
            upsert_section(conn, section, term_code, desc, prereqs, fmt, course_title)

        # Remove any CRNs that no longer exist in Banner for this term+subject
        live_crns = [s["courseReferenceNumber"] for s in sections]
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM courses
                WHERE term_code = %s AND subject = %s AND crn != ALL(%s)
            """, (term_code, code, live_crns))
            deleted = cur.rowcount
        if deleted:
            log.info(f"    Removed {deleted} stale sections for {code}")

        conn.commit()
        log.info(f"    Saved {len(sections)} sections for {code}")
        time.sleep(0.2)

    log.info(f"Done scraping {term_desc}")


def refresh_enrollment(conn, term_code: str, term_desc: str,
                       subjects_filter: list[str] | None = None):
    log.info(f"Enrollment refresh: {term_desc} ({term_code})")
    t0 = time.time()

    list_session = make_session(term_code)
    subjects = get_all_subjects(list_session, term_code)
    if subjects_filter:
        subjects = [s for s in subjects if s["code"] in subjects_filter]
    log.info(f"  {len(subjects)} subjects")

    def fetch_subject(subj):
        session = make_session(term_code)
        return subj["code"], search_courses(session, term_code, subj["code"])

    total = 0
    with ThreadPoolExecutor(max_workers=ENROLLMENT_WORKERS) as pool:
        futures = {pool.submit(fetch_subject, s): s for s in subjects}
        for future in as_completed(futures):
            code, sections = future.result()
            for section in sections:
                update_enrollment(conn, section, term_code)
            total += len(sections)
            log.info(f"  {code}: {len(sections)} sections")
    conn.commit()

    elapsed = time.time() - t0
    log.info(f"Enrollment refresh done: {total} sections updated in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NEU Banner course scraper")
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""),
                        help="PostgreSQL connection string (overrides DATABASE_URL env var)")
    parser.add_argument("--terms", nargs="*", help="Term codes to scrape (default: latest semester)")
    parser.add_argument("--subjects", nargs="*", help="Subject codes to scrape (default: all)")
    parser.add_argument("--list-terms", action="store_true", help="List available terms and exit")
    parser.add_argument("--enrollment", action="store_true",
                        help="Fast enrollment-only refresh (skips descriptions, prereqs, meetings)")
    args = parser.parse_args()

    if not args.dsn:
        parser.error("DATABASE_URL env var or --dsn required")

    conn = init_db(args.dsn)

    session = requests.Session()
    session.headers["User-Agent"] = "NEU-Course-Explorer/1.0"
    all_terms = get_all_terms(session)

    if args.list_terms:
        for t in all_terms:
            print(f"{t['code']}  {t['description']}")
        return

    if not args.terms:
        for t in all_terms:
            desc = t["description"]
            if "Semester" in desc and "View Only" not in desc and "CPS" not in desc:
                args.terms = [t["code"]]
                log.info(f"Auto-selected term: {desc} ({t['code']})")
                break

    if not args.terms:
        log.error("No terms found to scrape.")
        return

    term_map = {t["code"]: t["description"] for t in all_terms}
    for term_code in args.terms:
        term_desc = term_map.get(term_code, term_code)
        if args.enrollment:
            refresh_enrollment(conn, term_code, term_desc, subjects_filter=args.subjects)
        else:
            scrape_term(conn, term_code, term_desc, subjects_filter=args.subjects)

    conn.close()
    log.info("All done.")


if __name__ == "__main__":
    main()
