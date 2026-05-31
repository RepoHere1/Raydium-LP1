"""SUPER-BRAINIAC_POSSIBILITIES — scan, score, optional LIVE open, continuous loop."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.scanner import load_dotenv
    from raydium_lp1.super_brainiac.possibilities import (
        LOGIC_DOCS,
        analyze_create_pool_feasibility,
        load_brainiac_config,
        run_brainiac_cycle,
        scan_brainiac_universe,
        write_brainiac_report,
    )

    parser = argparse.ArgumentParser(description="SUPER-BRAINIAC_POSSIBILITIES experiment runner")
    parser.add_argument(
        "command",
        choices=("scan", "run-once", "loop", "docs", "create-pool-analysis"),
        help="scan=rank only; run-once=scan+optional LIVE; loop=continuous scan",
    )
    parser.add_argument("--execute-live", action="store_true", help="Open top pick on-chain (run-once / loop)")
    parser.add_argument("--interval", type=float, default=0, help="Loop seconds (0=use settings)")
    args = parser.parse_args()

    load_dotenv()

    if args.command == "docs":
        print(json.dumps(LOGIC_DOCS, indent=2))
        return 0
    if args.command == "create-pool-analysis":
        print(json.dumps(analyze_create_pool_feasibility(), indent=2))
        return 0

    cfg, scanner = load_brainiac_config()

    if args.command == "scan":
        report = scan_brainiac_universe(cfg=cfg, scanner=scanner)
        path = write_brainiac_report(report, cfg)
        print(json.dumps({"ok": True, "report_path": str(path), "top_pick": report.get("top_pick")}, indent=2))
        return 0

    if args.command == "run-once":
        if args.execute_live and get_mode() != "live":
            print(json.dumps({"ok": False, "error": "mode must be live for --execute-live"}, indent=2))
            return 1
        out = run_brainiac_cycle(execute_live=args.execute_live)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1

    interval = args.interval or cfg.continuous_interval_sec
    print(json.dumps({"loop": True, "interval_sec": interval}, indent=2), file=sys.stderr)
    while True:
        try:
            out = run_brainiac_cycle(execute_live=args.execute_live and get_mode() == "live")
            print(json.dumps(out, indent=2, default=str))
            if args.execute_live and out.get("ok") and (out.get("live_open") or {}).get("ok"):
                print("[brainiac] LIVE open succeeded; stopping loop.", file=sys.stderr)
                return 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        time.sleep(max(15.0, interval))


if __name__ == "__main__":
    raise SystemExit(main())
