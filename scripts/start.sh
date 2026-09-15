#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -e '.[dev]'
[ -f .env ] || cp .env.example .env
exec .venv/bin/python scripts/run.py
