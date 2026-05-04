# NEU Course Explorer

A course catalog browser for Northeastern University, similar to [courses.illinois.edu](https://courses.illinois.edu). Browse courses by subject, search by keyword or instructor, and see real-time enrollment across sections.

Live at **[neu-course-explorer.vercel.app](https://neu-course-explorer.vercel.app)**  

Data is pulled from the public NEU Banner API — no login required.

## Features

- Browse all subjects and courses for any term
- Search by course title, subject, or keyword
- Search by instructor name
- Per-section detail: enrollment, waitlist, meeting times, location, faculty, credits, section number
- Sections with different topics (e.g. Special Topics) grouped by title with a sidebar TOC
- Canonical course titles from the Banner course catalog (not section-specific overrides)
- Right-click / open-in-new-tab support on subject and course cards

## Stack

| Layer | Tech |
|-------|------|
| Scraper | Python, Requests, BeautifulSoup |
| API | FastAPI (Vercel serverless functions) |
| Database | PostgreSQL via [Neon](https://neon.tech) |
| Frontend | Vanilla HTML/CSS/JS (no build step, hosted on Vercel) |
| Enrollment cron | GitHub Actions (every 10 minutes) |

## Setup

**Requirements:** Python 3.11+, [uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/xianruizhong/Neu-Course-Explorer.git
cd neu-course-explorer

uv venv .venv
uv pip install --python .venv/bin/python -r api/requirements.txt
uv pip install --python .venv/bin/python -r scraper/requirements.txt
```

Create a `.env` file in the project root with your Neon connection strings:

```
DATABASE_URL=postgresql://...             # pooled — for the API
DATABASE_URL_UNPOOLED=postgresql://...    # direct — for the scraper
```

## Scraping

Run the scraper to populate the database. It fetches subjects, courses, sections, canonical course titles, descriptions, prerequisites, faculty, and meeting times from Banner. Stale sections (cancelled or removed from Banner) are automatically deleted on each run.

```bash
cd scraper

# Scrape a specific term (e.g. Fall 2026)
../.venv/bin/python scraper.py --terms 202710

# Scrape multiple terms
../.venv/bin/python scraper.py --terms 202630 202710

# List available term codes
../.venv/bin/python scraper.py --list-terms

# Scrape specific subjects only
../.venv/bin/python scraper.py --terms 202710 --subjects CS DS MATH
```

The scraper reads `DATABASE_URL` from the environment or `.env` file. Use the non-pooling URL for the scraper since it runs as a long-lived process (`--dsn` flag also accepted).

### Enrollment refresh

Refreshes only enrollment and waitlist numbers — much faster than a full scrape. Used by the GitHub Actions cron.

```bash
../.venv/bin/python scraper.py --enrollment
../.venv/bin/python scraper.py --enrollment --terms 202710
```

## Running locally

**Option 1 — Docker (no local Postgres needed):**

```bash
docker compose up
```

Then scrape into the container's database:

```bash
docker compose exec web bash -c "python -m scraper.scraper --dsn \$DATABASE_URL --terms 202710"
```

Site is at `http://localhost:8080`.

**Option 2 — bare metal:**

```bash
export DATABASE_URL=postgresql://user:password@localhost/neu_courses
cd scraper && ../.venv/bin/python scraper.py --terms 202710
cd .. && ./run.sh              # http://localhost:8999
PORT=3000 ./run.sh             # custom port
```

## Deployment

Production uses **Vercel** for the API and frontend, and **Neon** for the database.

### Vercel

1. Connect the GitHub repo to a Vercel project
2. Set **Output Directory** to `web` in Build & Output Settings
3. Add a Neon database via the Vercel dashboard (sets `POSTGRES_URL` automatically)
4. Push to `main` — Vercel deploys to production automatically

Any branch other than `main` gets a preview deployment URL automatically — useful for testing before merging.

### Enrollment cron (GitHub Actions)

Add `DATABASE_URL` (non-pooling connection string) as a repository secret under **Settings → Secrets → Actions**. The workflow file is already at `.github/workflows/enrollment.yml`.

> **Note:** Requires a public repository, or a private repo with sufficient Actions minutes (≈4,320 min/month at 10-minute intervals).

### Self-hosted (Linux server)

<details>
<summary>systemd + nginx</summary>

```bash
# Edit User= in the service file to match your username
sudo cp neu-course-explorer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now neu-course-explorer

sudo cp neu-course-explorer.nginx /etc/nginx/sites-available/neu-course-explorer
sudo ln -s /etc/nginx/sites-available/neu-course-explorer /etc/nginx/sites-enabled/
sudo certbot --nginx -d yourdomain.com
sudo nginx -s reload
```

</details>

<details>
<summary>Docker</summary>

```bash
docker compose up -d
```

The Docker setup includes a PostgreSQL service. Data is persisted in a named volume (`pgdata`). To stop without losing data: `docker compose stop`. To wipe everything: `docker compose down -v`.

</details>
