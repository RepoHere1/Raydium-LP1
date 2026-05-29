"""CLI: open one LIVE CLMM position (called from open_live_lp.ps1)."""

from __future__ import annotations

import json
import sys

from raydium_lp1.live_executor import live_readiness_check, open_clmm_candidate
from raydium_lp1.scanner import load_dotenv


def main() -> int:
    load_dotenv()
    ready = live_readiness_check()
    if not ready.get("ready_to_sign"):
        print(json.dumps({"ok": False, "blockers": ready.get("blockers")}, indent=2))
        return 1
    pool_id = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    sol = float(sys.argv[2]) if len(sys.argv) > 2 else 0.005
    result = open_clmm_candidate(pool_id=pool_id, input_amount_sol=sol)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
