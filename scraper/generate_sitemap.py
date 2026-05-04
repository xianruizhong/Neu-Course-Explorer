"""
Generates web/sitemap/sitemap.xml from the database.
Run after scraping a new term to keep the sitemap current.
"""

import os
import re
import sys
import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SITE_URL = "https://neu-course-explorer.vercel.app"
OUT_FILE = Path(__file__).parent.parent / "web" / "sitemap" / "sitemap.xml"
_TERM_RE = re.compile(r'(Spring|Summer\s*\d*|Fall)\s+(\d{4})', re.IGNORECASE)


def term_desc_to_path(desc):
    m = _TERM_RE.search(desc)
    if not m:
        return None
    season = re.sub(r'\s+', '', m.group(1).lower())
    return f"{m.group(2)}/{season}"


def main():
    dsn = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL", "")
    if not dsn:
        sys.exit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT code, description FROM terms ORDER BY code DESC LIMIT 2")
            terms = cur.fetchall()

            urls = [f"""  <url>
    <loc>{SITE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>"""]

            for term in terms:
                term_path = term_desc_to_path(term["description"])
                if not term_path:
                    continue
                cur.execute(
                    """SELECT DISTINCT subject, course_number
                       FROM courses WHERE term_code=%s
                       ORDER BY subject, course_number""",
                    (term["code"],),
                )
                for row in cur.fetchall():
                    url = f"{SITE_URL}/schedule/{term_path}/{row['subject']}/{row['course_number']}"
                    urls.append(f"""  <url>
    <loc>{url}</loc>
    <priority>0.7</priority>
  </url>""")
    finally:
        conn.close()

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xsi:schemaLocation="http://www.sitemaps.org/schemas/sitemap/0.9 http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>\n"

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(xml, encoding="utf-8")
    print(f"Wrote {len(urls)} URLs to {OUT_FILE}")


if __name__ == "__main__":
    main()
