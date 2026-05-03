#!/usr/bin/env bash
# NEU Course Explorer — start the API + frontend server
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv/bin/python"
PORT="${PORT:-8999}"

if [ -z "$DATABASE_URL" ]; then
  echo "Error: DATABASE_URL is not set."
  echo ""
  echo "Set it to your PostgreSQL connection string, e.g.:"
  echo "  export DATABASE_URL=postgresql://user:password@localhost/neu_courses"
  echo ""
  echo "Or start everything with Docker:"
  echo "  docker compose up"
  exit 1
fi

echo "Starting NEU Course Explorer on http://localhost:$PORT"
cd "$ROOT/api"
WEB_DIR="$ROOT/web" \
"$VENV" -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
