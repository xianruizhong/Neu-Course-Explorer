#!/usr/bin/env bash
# Nightly database update — re-scrapes all active terms
# Designed to be run via cron, e.g.:
#   0 3 * * * /shared/data/xzhong23/neu-course-explorer/scraper/update.sh >> /shared/data/xzhong23/neu-course-explorer/scraper/update.log 2>&1

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/../.venv/bin/python"
LOG_DIR="$SCRIPT_DIR"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "========================================"
echo "[$TIMESTAMP] Starting nightly update"
echo "========================================"

cd "$SCRIPT_DIR"

# Determine which terms to scrape:
# - The current active semester (no "View Only" in description)
# - Upcoming semester (if available)
TERMS=$("$PYTHON" - <<'EOF'
import requests, json

BASE = "https://nubanner.neu.edu/StudentRegistrationSsb/ssb"
resp = requests.get(f"{BASE}/classSearch/getTerms", params={"offset": 1, "max": 20}, timeout=15)
terms = resp.json()

selected = []
for t in terms:
    desc = t["description"]
    # Skip CPS quarters and Law semesters — too many to scrape nightly
    if any(x in desc for x in ["CPS", "Law", "Quarter"]):
        continue
    selected.append(t["code"])
    # Scrape at most 2 terms (current + next)
    if len(selected) >= 2:
        break

print(" ".join(selected))
EOF
)

if [ -z "$TERMS" ]; then
    echo "ERROR: Could not determine terms to scrape"
    exit 1
fi

echo "Terms to scrape: $TERMS"

for TERM in $TERMS; do
    echo ""
    echo "--- Scraping term $TERM ---"
    "$PYTHON" "$SCRIPT_DIR/scraper.py" --terms "$TERM"
done

echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Update complete."
