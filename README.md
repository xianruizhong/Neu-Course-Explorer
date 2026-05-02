# NEU Course Explorer

A course catalog browser for Northeastern University, similar to [courses.illinois.edu](https://courses.illinois.edu). Browse courses by subject, search by keyword or instructor, and see real-time enrollment across sections.

Data is pulled from the public NEU Banner API — no login required.

## Stack

| Layer | Tech |
|-------|------|
| Scraper | Python, Requests, BeautifulSoup |
| API | FastAPI + SQLite |
| Frontend | Vanilla HTML/CSS/JS (no build step) |

## Setup

**Requirements:** Python 3.11+, [uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/YOUR_USERNAME/neu-course-explorer.git
cd neu-course-explorer

# Create virtualenv and install dependencies
uv venv .venv
uv pip install --python .venv/bin/python -r api/requirements.txt
uv pip install --python .venv/bin/python -r scraper/requirements.txt
```

## Scraping

Run the scraper before starting the server. It fetches all subjects, courses, sections, descriptions, prerequisites, faculty, and meeting times from Banner.

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

### Enrollment refresh

For keeping enrollment numbers current without a full re-scrape (~30 seconds vs ~hours):

```bash
../.venv/bin/python scraper.py --enrollment
../.venv/bin/python scraper.py --enrollment --terms 202710
```

## Running locally

```bash
./run.sh              # http://localhost:8080
PORT=3000 ./run.sh    # custom port
```

## Deployment

### Systemd service (Linux server)

```bash
# Edit User= in the service file to match your username
sudo cp neu-course-explorer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now neu-course-explorer
```

### nginx + HTTPS

```bash
sudo cp neu-course-explorer.nginx /etc/nginx/sites-available/neu-course-explorer
sudo ln -s /etc/nginx/sites-available/neu-course-explorer /etc/nginx/sites-enabled/
sudo certbot --nginx -d yourdomain.com
sudo nginx -s reload
```

### Docker

```bash
docker compose up -d
```

The `scraper/` directory is mounted as a volume so the database is live without rebuilding the image.

### Vercel (frontend only)

The `vercel.json` proxies `/api/*` to a separately hosted backend. Update the `destination` URL before deploying:

```bash
vercel
```

### Enrollment cron (GitHub Actions)

See `.github/workflows/enrollment.yml` for a workflow that refreshes enrollment every 10 minutes. Requires `DATABASE_URL` set as a repository secret.

> **Note:** Requires a public repository or sufficient Actions minutes (4,320 min/month at 10-minute intervals).
