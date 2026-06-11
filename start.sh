#!/usr/bin/env bash
# Launch the globe: one process, one port. API + frontend on http://localhost:8090
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[globe] creating venv and installing dependencies…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

PORT="${PORT:-8090}"
echo "[globe] http://localhost:${PORT}  (live ingestion starts in background)"
exec .venv/bin/uvicorn backend.server:app --host 127.0.0.1 --port "$PORT"
