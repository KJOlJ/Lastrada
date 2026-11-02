#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v python3.12 >/dev/null 2>&1; then
  exec python3.12 run-local.py
elif command -v python3 >/dev/null 2>&1; then
  exec python3 run-local.py
else
  echo "Install Python 3.12 from python.org, then open this launcher again."
  exit 1
fi
