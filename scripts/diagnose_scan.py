#!/usr/bin/env python3
"""One-shot health check: LP planner edge cases + optional live Raydium scan tail.

Exit 0 = safe to run your full Windows scan. Exit 1 = fix reported blockers first.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _check_lp_skew() -> list[str]:
    from raydium_lp1 import lp_range_planner

    errors: list[str] = []
    cases = [
        ({"tier": "exit_now"}, True, "exit_now without detective"),
        ({"tier": "hot", "detective": {"inflow_bias": 40}}, True, "detective + tier"),
        (None, True, "none momentum"),
    ]
    for mom, use, label in cases:
        try:
            sk, notes = lp_range_planner.momentum_skew(mom, use_momentum=use)
            lp_range_planner.plan_for_pool(
                {
                    "id": "diag",
                    "mint_a_symbol": "SOL",
                    "mint_b_symbol": "TEST",
                    "liquidity_usd": 5000,
                    "volume_24h_usd": 1000,
                    "type": "Concentrated",
                    "subtypes": ["Clmm"],
                    "raw": {"day": {"priceMin": 1.0, "priceMax": 1.1, "volume": 1000}},
                },
                mom if isinstance(mom, dict) else None,
                lp_range_planner.LPPlannerConfig(enabled=True),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
        else:
            print(f"  OK  lp skew/plan — {label} (skew={sk:.2f}, notes={notes})")
    return errors


def _live_tail(*, pages: int, page_size: int, config_path: Path) -> list[str]:
    from raydium_lp1.scanner import ScannerConfig, scan

    errors: list[str] = []
    cfg = ScannerConfig.from_file(config_path)
    object.__setattr__(cfg, "pages", pages)
    object.__setattr__(cfg, "page_size", page_size)
    object.__setattr__(cfg, "lp_planning_enabled", True)
    object.__setattr__(cfg, "momentum_enabled", True)
    object.__setattr__(cfg, "require_sell_route", False)
    object.__setattr__(cfg, "min_apr", 50.0)
    object.__setattr__(cfg, "min_liquidity_usd", 100.0)
    object.__setattr__(cfg, "min_volume_24h_usd", 10.0)

    print(f"  … live tail scan pages={pages} page_size={page_size} lp_planning=ON")
    try:
        report = scan(cfg, wallet_config=None, verdict_stream=None, write_rejections_override=False)
    except Exception as exc:  # noqa: BLE001
        return [f"live scan: {exc}"]

    n_cand = int(report.get("candidate_count") or 0)
    n_rej = int(report.get("rejected_count") or 0)
    print(f"  OK  live tail — scanned={report.get('scanned_count')} candidates={n_cand} rejected={n_rej}")
    for pool in report.get("candidates") or []:
        if pool.get("lp_placement_plan") is None:
            errors.append(f"candidate {pool.get('id')} missing lp_placement_plan")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Raydium-LP1 scan diagnostics")
    parser.add_argument("--live", action="store_true", help="Hit Raydium API for a short scan tail")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "settings.json")
    args = parser.parse_args()

    print("Raydium-LP1 diagnose_scan")
    print("=" * 48)

    all_errors: list[str] = []
    print("\n[1] LP planner (momentum_skew / plan_for_pool)")
    all_errors.extend(_check_lp_skew())

    if args.live:
        print("\n[2] Live Raydium tail (needs network)")
        if not args.config.exists():
            all_errors.append(f"missing config: {args.config}")
        else:
            all_errors.extend(
                _live_tail(pages=max(1, args.pages), page_size=max(1, args.page_size), config_path=args.config)
            )
    else:
        print("\n[2] Live tail skipped (pass --live)")

    print("\n" + "=" * 48)
    if all_errors:
        print("FAIL")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    print("PASS — safe to run full scan on your machine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
