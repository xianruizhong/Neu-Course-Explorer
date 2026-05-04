"""
Generates web/sitemap/sitemap.xml.
Hash-fragment URLs (#view=detail&...) are stripped by Google, so only the
homepage is included. Run after scraping if the site URL ever changes.
"""

from pathlib import Path

SITE_URL = "https://neu-course-explorer.vercel.app"
OUT_FILE = Path(__file__).parent.parent / "web" / "sitemap" / "sitemap.xml"

XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""

if __name__ == "__main__":
    OUT_FILE.write_text(XML, encoding="utf-8")
    print(f"Wrote {OUT_FILE}")
