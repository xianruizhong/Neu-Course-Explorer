# NEU Course Explorer

A course catalog browser for Northeastern University, similar to [courses.illinois.edu](https://courses.illinois.edu). Browse courses by subject, search by keyword or instructor, and see real-time enrollment across sections.

Data is pulled from the public NEU Banner API — no login required.

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
git clone https://github.com/YOUR_USERNAME/neu-course-explorer.git
cd neu-course-explorer

uv venv .venv
uv pip install --python .venv/bin/python -r api/requirements.txt
uv pip install --python .venv/bin/python -r scraper/requirements.txt
```

Create a `.env` file in the project root with your Neon connection strings:

```
DATABASE_URL=postgresql://...        # pooled — for the API
POSTGRES_URL_NON_POOLING=postgresql://...  # direct — for the scraper
```

## Scraping

Run the scraper to populate the database. It fetches all subjects, courses, sections, descriptions, prerequisites, faculty, and meeting times from Banner.

```bash
cd scraper

# Scrape the current semester (auto-detected)
../.venv/bin/python scraper.py

# Scrape a specific term
../.venv/bin/python scraper.py --terms 202710

# List available term codes
../.venv/bin/python scraper.py --list-terms

# Scrape specific subjects only
../.venv/bin/python scraper.py --terms 202710 --subjects CS DS MATH
```

The scraper reads `DATABASE_URL` from the environment (or `.env` file via python-dotenv). Use the non-pooling URL for the scraper since it runs as a long-lived process.

### Enrollment refresh

Refreshes only enrollment numbers — much faster than a full scrape (~30s vs hours). Used by the GitHub Actions cron.

```bash
../.venv/bin/python scraper.py --enrollment
../.venv/bin/python scraper.py --enrollment --terms 202710
```

## Running locally

```bash
./run.sh              # http://localhost:8080
PORT=3000 ./run.sh    # custom port
```

The local server serves both the API and the frontend. Requires `DATABASE_URL` and `WEB_DIR` to be set (handled by `run.sh`).

## Deployment

The production deployment uses **Vercel** for the frontend and API, and **Neon** for the database.

### Vercel

1. Connect the GitHub repo to a Vercel project
2. Set **Output Directory** to `web` in Build & Output Settings
3. Add a Neon database via the Vercel dashboard (sets `POSTGRES_URL` automatically)
4. Push to `main` — Vercel deploys automatically

The `vercel.json` routes all `/api/*` requests to `api/index.py` (FastAPI serverless function). The frontend is served from `web/`.

### Enrollment cron (GitHub Actions)

Create `.github/workflows/enrollment.yml`:

```yaml
name: Enrollment Refresh
on:
  schedule:
    - cron: '*/10 * * * *'
  workflow_dispatch:

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r scraper/requirements.txt
      - run: python scraper/scraper.py --enrollment
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

Add `DATABASE_URL` (use the non-pooling connection string) as a repository secret under **Settings → Secrets → Actions**.

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

The `scraper/` directory is mounted as a volume so the database is live without rebuilding the image. Note: the Docker setup still uses SQLite — update `docker-compose.yml` if you want to point it at Neon instead.

</details>
