#!/usr/bin/env python3
"""Interactive Brainiac LIVE open wizard — remembers answers except pool id.

Paths (architecture):
  Core order type:  src/raydium_lp1/lp_brainiac_cursor_success.py
  Open runner:      src/raydium_lp1/brainiac_open_runner.py
  Wizard state:     config/brainiac_wizard_last.json
  This wizard:      scripts/brainiac_open_wizard.py
  Quick CLI open:   scripts/_brainiac_open_once_pool.py <pool> <usd>
  Pretrade only:    scripts/_brainiac_pretrade_analysis.py <pool> <usd>
  Settings helper: scripts/set_brainiac_strategy.ps1

Usage (CMD):
  cd /d C:\\Users\\Taylor\\Raydium-LP1
  .\\brainiac_wizard.cmd

  REM Or one line from anywhere:
  cd /d C:\\Users\\Taylor\\Raydium-LP1 && brainiac_wizard.cmd -PoolId YOUR_POOL_ID -DepositUsd 4 -Yes

  REM LIVE: asks all wizard variables, skips "type LIVE" confirm only:
  brainiac_wizard.cmd -Live

  REM Optional CLI overrides after prompts:
  brainiac_wizard.cmd -Live -PoolId YOUR_POOL_ID -DepositUsd 1

Usage (Python from repo root):
  python scripts/brainiac_open_wizard.py
  python scripts/brainiac_open_wizard.py --live --deposit-usd 1
  python scripts/brainiac_open_wizard.py --live --pool POOL_ID --deposit-usd 1
  python scripts/brainiac_open_wizard.py --help-fields
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from raydium_lp1.brainiac_open_runner import (  # noqa: E402
    BrainiacOpenRequest,
    apply_brainiac_strategy_settings,
    execute_brainiac_open,
    preview_brainiac_open,
)
from raydium_lp1.brainiac_wizard_preview import print_live_report_summary, print_preview_summary  # noqa: E402
from raydium_lp1.brainiac_wizard_state import (  # noqa: E402
    POOL_PLACEHOLDER,
    BrainiacWizardAnswers,
    load_wizard_state,
    print_field_help_catalog,
    run_interactive_wizard,
    save_wizard_state,
)


def _normalize_fraction(v: float) -> float:
    if v > 1.0:
        return v / 100.0
    return v


def resolve_pool_and_answers(args: argparse.Namespace) -> tuple[str, BrainiacWizardAnswers]:
    """Interactive wizard (default), saved-state CLI (--non-interactive), or --live (wizard + no confirm)."""

    if args.non_interactive:
        from raydium_lp1.brainiac_wizard_state import apply_auto_policy_to_answers

        answers = load_wizard_state()
        pool_id = (args.pool or POOL_PLACEHOLDER).strip()
        if args.deposit_usd is not None:
            answers.deposit_usd = args.deposit_usd
        if answers.use_auto_live_policy and pool_id != POOL_PLACEHOLDER:
            answers = apply_auto_policy_to_answers(pool_id, answers)
        return pool_id, answers

    cli_pool = (args.pool or "").strip()
    pool_id, answers = run_interactive_wizard(
        pool_id=cli_pool if cli_pool and cli_pool != POOL_PLACEHOLDER else None,
        live_mode=bool(args.live),
    )
    if args.deposit_usd is not None:
        answers.deposit_usd = float(args.deposit_usd)
    return pool_id, answers


def main() -> int:
    parser = argparse.ArgumentParser(description="Brainiac LIVE open wizard")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Ask all wizard fields, then sign LIVE without typing LIVE at confirm",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use saved config/brainiac_wizard_last.json; pool must be set via --pool",
    )
    parser.add_argument("--pool", default="", help="Pool id (optional for --live; prompts if omitted)")
    parser.add_argument("--deposit-usd", type=float, default=None)
    parser.add_argument("--yes", action="store_true", help="Skip LIVE confirm prompt")
    parser.add_argument(
        "--help-fields",
        action="store_true",
        help="Print descriptions for every wizard variable and exit",
    )
    args = parser.parse_args()

    if args.help_fields:
        print_field_help_catalog()
        return 0

    if args.live:
        args.yes = True

    try:
        pool_id, answers = resolve_pool_and_answers(args)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    answers.fund_non_pay_fraction = _normalize_fraction(float(answers.fund_non_pay_fraction))
    save_wizard_state(answers)

    if pool_id == POOL_PLACEHOLDER:
        print(json.dumps({"ok": False, "error": "Replace ENTER_POOL_ADDRESS_HERE with a real pool id"}, indent=2))
        return 1

    if answers.apply_brainiac_strategy:
        strat = apply_brainiac_strategy_settings()
        if not strat.get("ok"):
            if answers.dry_run_preview_only:
                print(
                    json.dumps(
                        {"warning": "set_brainiac_strategy failed (preview continues)", "detail": strat},
                        indent=2,
                    ),
                    file=sys.stderr,
                )
            else:
                print(json.dumps({"ok": False, "error": "set_brainiac_strategy failed", "detail": strat}, indent=2))
                return 1

    req = BrainiacOpenRequest.from_wizard(pool_id, answers)

    if answers.dry_run_preview_only:
        report = preview_brainiac_open(req)
        print_preview_summary(report)
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("ok") else 1

    if not args.yes:
        confirm = input('Type LIVE to sign on-chain (anything else cancels): ').strip()
        if confirm != "LIVE":
            print(json.dumps({"ok": False, "error": "cancelled; confirm with LIVE"}, indent=2))
            return 1

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
