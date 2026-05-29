"""List candidates from reports/latest.json (used by open_live_lp.ps1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LATEST = REPO / "reports" / "latest.json"


def main() -> int:
    if not LATEST.is_file():
        print("Run scan first: .\\scripts\\run_scan.ps1 -WriteReports", file=sys.stderr)
        return 1
    data = json.loads(LATEST.read_text(encoding="utf-8"))
    cands = data.get("candidates") or []
    if not cands:
        print("  (none — tune gates and re-scan)")
        return 0
    for i, c in enumerate(cands, 1):
        if not isinstance(c, dict):
            continue
        pair = f"{c.get('mint_a_symbol')}/{c.get('mint_b_symbol')}"
        mom = c.get("momentum") if isinstance(c.get("momentum"), dict) else {}
        tier = mom.get("tier") or "?"
        print(
            f"  [{i}] {c.get('id')}  {pair}  APR={c.get('apr')}%  "
            f"TVL=${c.get('liquidity_usd')}  mom={tier}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
