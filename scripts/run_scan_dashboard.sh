#!/usr/bin/env bash
# Scanner loop writing reports/dashboard.json; reloads config each cycle for the web UI.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

CONFIG="${CONFIG:-config/settings.json}"
INTERVAL="${INTERVAL:-60}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "python3 not found" >&2
  exit 1
fi

exec "$PY" scripts/scan_raydium_lps.py \
  --config "$CONFIG" \
  --dashboard \
  --loop \
  --interval "$INTERVAL" \
  --reload-config-each-scan \
  "$@"
