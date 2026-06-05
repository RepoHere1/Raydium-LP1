"""One-shot Brainiac LIVE open + USD report (pool/deposit via argv).

Prefer the wizard for remembered settings:
  python scripts/brainiac_open_wizard.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL_ID = sys.argv[1] if len(sys.argv) > 1 else ""
DEPOSIT_USD = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5


def main() -> int:
    from raydium_lp1.brainiac_open_runner import BrainiacOpenRequest, execute_brainiac_open
    from raydium_lp1.brainiac_wizard_state import load_wizard_state

    if not POOL_ID:
        print(json.dumps({"ok": False, "error": "pool id required"}, indent=2))
        return 1

    saved = load_wizard_state()
    req = BrainiacOpenRequest.from_wizard(POOL_ID, saved)
    req.deposit_usd = DEPOSIT_USD

    report = execute_brainiac_open(req)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
