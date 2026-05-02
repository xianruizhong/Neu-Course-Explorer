#!/usr/bin/env bash
# NEU Course Explorer — start the API + frontend server
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv/bin/python"
PORT="${PORT:-8080}"

if [ ! -f "$ROOT/scraper/courses.db" ]; then
  echo "No database found. Run the scraper first:"
  echo "  cd $ROOT/scraper && $VENV scraper.py"
  exit 1
fi

echo "Starting NEU Course Explorer on http://localhost:$PORT"
cd "$ROOT/api"
DB_PATH="$ROOT/scraper/courses.db" \
WEB_DIR="$ROOT/web" \
"$VENV" -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
