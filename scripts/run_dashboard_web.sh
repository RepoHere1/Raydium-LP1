#!/usr/bin/env bash
# Local funnel + settings UI (127.0.0.1 only). Pair with scanner --dashboard --loop --reload-config-each-scan.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

PORT="${PORT:-8844}"
HOST="${HOST:-127.0.0.1}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "python3 not found" >&2
  exit 1
fi

exec "$PY" -m raydium_lp1.dashboard_web --host "$HOST" --port "$PORT" "$@"
