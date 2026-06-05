#!/usr/bin/env python3
"""One-shot Brainiac LIVE execute (non-interactive) for a given pool + deposit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL_ID = sys.argv[1] if len(sys.argv) > 1 else ""
DEPOSIT_USD = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0


def main() -> int:
    from raydium_lp1.brainiac_open_runner import (
        BrainiacOpenRequest,
        apply_brainiac_strategy_settings,
        execute_brainiac_open,
    )
    from raydium_lp1.brainiac_wizard_preview import print_live_report_summary
    from raydium_lp1.brainiac_wizard_state import (
        apply_auto_policy_to_answers,
        load_wizard_state,
    )

    if not POOL_ID:
        print(json.dumps({"ok": False, "error": "pool id required"}, indent=2))
        return 1

    strat = apply_brainiac_strategy_settings()
    if not strat.get("ok"):
        print(json.dumps({"ok": False, "error": "strategy settings failed", "detail": strat}, indent=2))
        return 1

    answers = load_wizard_state()
    answers.deposit_usd = DEPOSIT_USD
    answers.dry_run_preview_only = False
    answers = apply_auto_policy_to_answers(POOL_ID, answers)

    req = BrainiacOpenRequest.from_wizard(POOL_ID, answers)
    report = execute_brainiac_open(req)

    out_path = REPO / "reports" / "brainiac_wizard_last_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print_live_report_summary(report)
    print(json.dumps(report, indent=2, default=str))
    print(f"\nReport saved: {out_path}", file=sys.stderr)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
