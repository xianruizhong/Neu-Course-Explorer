"""
NEU Banner Course Scraper
Fetches course data from nubanner.neu.edu (no login required).
Stores everything in a SQLite database.
"""

import requests
import sqlite3
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
MAX_WORKERS = 4   # concurrent detail fetches — keep gentle on the server
MAX_RETRIES = 3   # retries for transient timeouts


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS terms (
        code        TEXT PRIMARY KEY,
        description TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS subjects (
        code        TEXT NOT NULL,
        description TEXT NOT NULL,
        term_code   TEXT NOT NULL REFERENCES terms(code),
        PRIMARY KEY (code, term_code)
    );

    CREATE TABLE IF NOT EXISTS courses (
        crn                     TEXT NOT NULL,
        term_code               TEXT NOT NULL REFERENCES terms(code),
        subject                 TEXT NOT NULL,
        subject_description     TEXT,
        course_number           TEXT NOT NULL,
        title                   TEXT,
        credit_hour_low         REAL,
        credit_hour_high        REAL,
        campus                  TEXT,
        schedule_type           TEXT,
        part_of_term            TEXT,
        enrollment              INTEGER,
        max_enrollment          INTEGER,
        seats_available         INTEGER,
        wait_count              INTEGER,
        wait_capacity           INTEGER,
        wait_available          INTEGER,
        open_section            INTEGER,
        description             TEXT,
        prerequisites           TEXT,
        scraped_at              TEXT,
        PRIMARY KEY (crn, term_code)
    );

    CREATE TABLE IF NOT EXISTS meetings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        crn             TEXT NOT NULL,
        term_code       TEXT NOT NULL,
        begin_time      TEXT,
        end_time        TEXT,
        start_date      TEXT,
        end_date        TEXT,
        building        TEXT,
        building_desc   TEXT,
        room            TEXT,
        monday          INTEGER,
        tuesday         INTEGER,
        wednesday       INTEGER,
        thursday        INTEGER,
        friday          INTEGER,
        saturday        INTEGER,
        sunday          INTEGER,
        schedule_type   TEXT,
        FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code)
    );

    CREATE TABLE IF NOT EXISTS faculty (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        crn             TEXT NOT NULL,
        term_code       TEXT NOT NULL,
        banner_id       TEXT,
        name            TEXT,
        email           TEXT,
        primary_ind     INTEGER,
        FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code)
    );

    CREATE TABLE IF NOT EXISTS section_attributes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        crn             TEXT NOT NULL,
        term_code       TEXT NOT NULL,
        code            TEXT,
        description     TEXT,
        FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code)
    );

    CREATE INDEX IF NOT EXISTS idx_courses_term    ON courses(term_code);
    CREATE INDEX IF NOT EXISTS idx_courses_subject ON courses(subject, term_code);
    CREATE INDEX IF NOT EXISTS idx_courses_number  ON courses(course_number);
    CREATE VIRTUAL TABLE IF NOT EXISTS courses_fts USING fts5(
        crn, term_code, subject, title, description,
        content='courses', content_rowid='rowid'
    );
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Banner API helpers
# ---------------------------------------------------------------------------

def make_session(term_code: str) -> requests.Session:
    """Create a requests session with a Banner term cookie."""
    session = requests.Session()
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
    """Fetch all sections for a subject in a term (paginated)."""
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


def _post_with_retry(session: requests.Session, url: str, data: dict) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, data=data, timeout=20)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)  # exponential backoff: 1s, 2s
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
        text = section.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()
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
        text = section.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
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

def upsert_section(conn: sqlite3.Connection, section: dict, term_code: str,
                   description: str, prerequisites: str, fmt: list[dict]):
    crn = section["courseReferenceNumber"]
    now = datetime.utcnow().isoformat()

    conn.execute("""
        INSERT OR REPLACE INTO courses (
            crn, term_code, subject, subject_description, course_number, title,
            credit_hour_low, credit_hour_high, campus, schedule_type, part_of_term,
            enrollment, max_enrollment, seats_available,
            wait_count, wait_capacity, wait_available, open_section,
            description, prerequisites, scraped_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
        1 if section.get("openSection") else 0,
        description, prerequisites, now,
    ))

    # Delete and re-insert meetings / faculty / attributes (fresh data)
    conn.execute("DELETE FROM meetings WHERE crn=? AND term_code=?", (crn, term_code))
    conn.execute("DELETE FROM faculty WHERE crn=? AND term_code=?", (crn, term_code))
    conn.execute("DELETE FROM section_attributes WHERE crn=? AND term_code=?", (crn, term_code))

    seen_faculty = set()
    for mf in fmt:
        mt = mf.get("meetingTime", {})
        conn.execute("""
            INSERT INTO meetings
            (crn, term_code, begin_time, end_time, start_date, end_date,
             building, building_desc, room,
             monday, tuesday, wednesday, thursday, friday, saturday, sunday,
             schedule_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            crn, term_code,
            mt.get("beginTime"), mt.get("endTime"),
            mt.get("startDate"), mt.get("endDate"),
            mt.get("building"), mt.get("buildingDescription"), mt.get("room"),
            1 if mt.get("monday") else 0,
            1 if mt.get("tuesday") else 0,
            1 if mt.get("wednesday") else 0,
            1 if mt.get("thursday") else 0,
            1 if mt.get("friday") else 0,
            1 if mt.get("saturday") else 0,
            1 if mt.get("sunday") else 0,
            mt.get("meetingScheduleType"),
        ))
        for f in mf.get("faculty", []):
            # fmt repeats faculty across meeting rows — deduplicate by bannerId
            bid = f.get("bannerId")
            if bid in seen_faculty:
                continue
            seen_faculty.add(bid)
            conn.execute("""
                INSERT INTO faculty (crn, term_code, banner_id, name, email, primary_ind)
                VALUES (?,?,?,?,?,?)
            """, (
                crn, term_code,
                bid, f.get("displayName"), f.get("emailAddress"),
                1 if f.get("primaryIndicator") else 0,
            ))

    for attr in section.get("sectionAttributes", []):
        conn.execute("""
            INSERT INTO section_attributes (crn, term_code, code, description)
            VALUES (?,?,?,?)
        """, (crn, term_code, attr.get("code"), attr.get("description")))


def fetch_details_batch(sections: list[dict], term_code: str, session: requests.Session):
    """Fetch description, prereqs, and faculty/meeting times for each section concurrently."""
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


def update_enrollment(conn: sqlite3.Connection, section: dict, term_code: str):
    conn.execute("""
        UPDATE courses SET
            enrollment=?, max_enrollment=?, seats_available=?,
            wait_count=?, wait_capacity=?, wait_available=?,
            open_section=?, scraped_at=?
        WHERE crn=? AND term_code=?
    """, (
        section.get("enrollment"), section.get("maximumEnrollment"),
        section.get("seatsAvailable"),
        section.get("waitCount"), section.get("waitCapacity"),
        section.get("waitAvailable"),
        1 if section.get("openSection") else 0,
        datetime.utcnow().isoformat(),
        section["courseReferenceNumber"], term_code,
    ))


ENROLLMENT_WORKERS = 10  # concurrent subject fetches for enrollment refresh


def refresh_enrollment(conn: sqlite3.Connection, term_code: str, term_desc: str,
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


def scrape_term(conn: sqlite3.Connection, term_code: str, term_desc: str,
                subjects_filter: list[str] | None = None):
    log.info(f"Scraping term: {term_desc} ({term_code})")

    # Use a shared session just for listing subjects/terms
    list_session = make_session(term_code)

    # Save term
    conn.execute("INSERT OR REPLACE INTO terms (code, description) VALUES (?,?)",
                 (term_code, term_desc))
    conn.commit()

    subjects = get_all_subjects(list_session, term_code)
    log.info(f"  Found {len(subjects)} subjects")

    for subj in subjects:
        code = subj["code"]
        if subjects_filter and code not in subjects_filter:
            continue

        conn.execute("""
            INSERT OR REPLACE INTO subjects (code, description, term_code)
            VALUES (?,?,?)
        """, (code, subj["description"], term_code))

        log.info(f"  Fetching subject {code} ...")
        # Fresh session per subject — Banner's session state is sticky;
        # reusing a session across subjects returns stale filtered results.
        session = make_session(term_code)
        sections = search_courses(session, term_code, code)
        log.info(f"    {len(sections)} sections found")

        if not sections:
            conn.commit()
            continue

        # Fetch description + prereqs for all sections concurrently
        details = fetch_details_batch(sections, term_code, session)

        for section in sections:
            crn = section["courseReferenceNumber"]
            desc, prereqs, fmt = details.get(crn, ("", "", []))
            upsert_section(conn, section, term_code, desc, prereqs, fmt)

        conn.commit()
        log.info(f"    Saved {len(sections)} sections for {code}")
        time.sleep(0.2)  # gentle rate limiting per subject

    # Rebuild FTS index
    log.info("  Rebuilding FTS index ...")
    conn.execute("INSERT INTO courses_fts(courses_fts) VALUES('rebuild')")
    conn.commit()
    log.info(f"Done scraping {term_desc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NEU Banner course scraper")
    parser.add_argument("--db", default="courses.db", help="SQLite database path")
    parser.add_argument("--terms", nargs="*", help="Term codes to scrape (default: latest semester)")
    parser.add_argument("--subjects", nargs="*", help="Subject codes to scrape (default: all)")
    parser.add_argument("--list-terms", action="store_true", help="List available terms and exit")
    parser.add_argument("--enrollment", action="store_true", help="Fast enrollment-only refresh (skips descriptions, prereqs, meetings)")
    args = parser.parse_args()

    conn = init_db(args.db)

    # Use a generic session just for listing terms
    session = requests.Session()
    session.headers["User-Agent"] = "NEU-Course-Explorer/1.0"
    all_terms = get_all_terms(session)

    if args.list_terms:
        for t in all_terms:
            print(f"{t['code']}  {t['description']}")
        return

    # Default: scrape the most recent full semester (not CPS quarter, not View Only)
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
