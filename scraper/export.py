"""
Export SQLite database to static JSON files for GitHub Pages hosting.

Output structure (written to --out-dir, default ../docs/data):
  data/terms.json                          — list of terms
  data/{term}/subjects.json                — subjects for a term
  data/{term}/index.json                   — lightweight search index (title + snippet)
  data/{term}/{subject}.json               — all courses + sections for a subject
"""

import sqlite3
import json
import os
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))  # compact — saves space


def export(db_path: str, out_dir: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # ── Terms ──────────────────────────────────────────────────────────────
    terms = [dict(r) for r in conn.execute(
        "SELECT code, description FROM terms ORDER BY code DESC"
    ).fetchall()]
    write_json(out_dir / "terms.json", terms)
    log.info(f"Exported {len(terms)} terms")

    for term in terms:
        term_code = term["code"]
        term_dir = out_dir / term_code

        # ── Subjects ───────────────────────────────────────────────────────
        subjects = [dict(r) for r in conn.execute(
            "SELECT code, description FROM subjects WHERE term_code=? ORDER BY description",
            (term_code,)
        ).fetchall()]
        if not subjects:
            continue
        write_json(term_dir / "subjects.json", subjects)

        # ── Per-subject files ──────────────────────────────────────────────
        search_index = []  # lightweight: one entry per unique course

        seen_courses = set()

        for subj in subjects:
            subj_code = subj["code"]

            # All sections for this subject
            rows = conn.execute(
                "SELECT * FROM courses WHERE term_code=? AND subject=? ORDER BY course_number, crn",
                (term_code, subj_code)
            ).fetchall()

            if not rows:
                write_json(term_dir / f"{subj_code}.json", [])
                continue

            courses_map = {}  # course_number → course dict with sections list

            for row in rows:
                d = dict(row)
                crn = d["crn"]
                cn = d["course_number"]

                if cn not in courses_map:
                    courses_map[cn] = {
                        "subject": d["subject"],
                        "subject_description": d["subject_description"],
                        "course_number": cn,
                        "title": d["title"],
                        "credit_hour_low": d["credit_hour_low"],
                        "credit_hour_high": d["credit_hour_high"],
                        "description": d["description"],
                        "prerequisites": d["prerequisites"],
                        "sections": [],
                    }

                    # Add to search index once per unique course
                    course_key = f"{term_code}:{subj_code}:{cn}"
                    if course_key not in seen_courses:
                        seen_courses.add(course_key)
                        snippet = (d["description"] or "")[:200]
                        search_index.append({
                            "s": subj_code,
                            "n": cn,
                            "t": d["title"] or "",
                            "d": snippet,
                        })

                # Meetings
                meetings = [dict(m) for m in conn.execute(
                    "SELECT begin_time, end_time, start_date, end_date, building, "
                    "building_desc, room, monday, tuesday, wednesday, thursday, "
                    "friday, saturday, sunday, schedule_type "
                    "FROM meetings WHERE crn=? AND term_code=?",
                    (crn, term_code)
                ).fetchall()]

                # Faculty
                faculty = [dict(f) for f in conn.execute(
                    "SELECT name, email, primary_ind FROM faculty WHERE crn=? AND term_code=?",
                    (crn, term_code)
                ).fetchall()]

                # Attributes
                attributes = [dict(a) for a in conn.execute(
                    "SELECT code, description FROM section_attributes WHERE crn=? AND term_code=?",
                    (crn, term_code)
                ).fetchall()]

                section = {
                    "crn": crn,
                    "campus": d["campus"],
                    "schedule_type": d["schedule_type"],
                    "part_of_term": d["part_of_term"],
                    "enrollment": d["enrollment"],
                    "max_enrollment": d["max_enrollment"],
                    "seats_available": d["seats_available"],
                    "wait_count": d["wait_count"],
                    "wait_capacity": d["wait_capacity"],
                    "open_section": bool(d["open_section"]),
                    "meetings": meetings,
                    "faculty": faculty,
                    "attributes": attributes,
                }
                courses_map[cn]["sections"].append(section)

            courses = list(courses_map.values())
            write_json(term_dir / f"{subj_code}.json", courses)

        write_json(term_dir / "index.json", search_index)
        log.info(f"  {term_code}: {len(subjects)} subjects, {len(search_index)} unique courses")

    conn.close()
    log.info(f"Export complete → {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Export DB to static JSON for GitHub Pages")
    parser.add_argument("--db", default="courses.db")
    parser.add_argument("--out-dir", default="../docs/data")
    args = parser.parse_args()

    export(args.db, Path(args.out_dir))


if __name__ == "__main__":
    main()
