#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v node >/dev/null
command -v npm >/dev/null
command -v python3 >/dev/null
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
.venv/bin/python scripts/configure.py
npx remotion browser ensure
npx playwright install chromium
printf '%s\n' 'Setup finished. Fill .env; configure Codex CLI/login; npm run bind; npm run bot.'
