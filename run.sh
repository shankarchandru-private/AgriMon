#!/usr/bin/env bash
# AgriMon Evolution 1 - macOS/Linux launcher. First run creates .venv and installs requirements.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtual environment (.venv)..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ ! -f .env ]; then
  echo "WARNING: no .env file: copy .env.example to .env and set OPENAI_API_KEY." >&2
fi
exec .venv/bin/python -m agrimon
