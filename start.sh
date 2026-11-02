#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PORT="${LUNA_PORT:-8000}"
echo "Opening http://localhost:$PORT. Add your API keys in Settings. Press Ctrl+C to stop."
(sleep 2; .venv/bin/python -m webbrowser "http://localhost:$PORT" >/dev/null 2>&1) &
exec .venv/bin/python -m uvicorn luna.app:app --host 127.0.0.1 --port "$PORT"
