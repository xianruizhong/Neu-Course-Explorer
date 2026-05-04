"""
Generates web/sitemap.xml from the database.
Run after scraping to keep the sitemap current.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SITE_URL = "https://neu-course-explorer.vercel.app"
OUT_FILE = Path(__file__).parent.parent / "web" / "sitemap.xml"


def main():
    dsn = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL", "")
    if not dsn:
        sys.exit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT code FROM terms ORDER BY code DESC LIMIT 2")
            term_codes = [r["code"] for r in cur.fetchall()]

            urls = [f"""  <url>
    <loc>{SITE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>"""]

            for code in term_codes:
                cur.execute(
                    """SELECT DISTINCT subject, course_number
                       FROM courses WHERE term_code=%s
                       ORDER BY subject, course_number""",
                    (code,),
                )
                for row in cur.fetchall():
                    frag = (
                        f"view=detail&amp;term={code}"
                        f"&amp;subject={row['subject']}"
                        f"&amp;number={row['course_number']}"
                    )
                    urls.append(f"""  <url>
    <loc>{SITE_URL}/#{frag}</loc>
    <priority>0.7</priority>
  </url>""")
    finally:
        conn.close()

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>\n"

    OUT_FILE.write_text(xml, encoding="utf-8")
    print(f"Wrote {len(urls)} URLs to {OUT_FILE}")


if __name__ == "__main__":
    main()
