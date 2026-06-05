"""Pre-LIVE multi-refresh consensus gate for Brainiac 80% skew placement.

Before signing, re-fetch the pool N times, re-run the skew grid each time, and
only proceed when skew is stable and in-range overlap stays above threshold.
"""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime
from typing import Any, Mapping

DEFAULT_SCAN_COUNT = 5
DEFAULT_SCAN_DELAY_SEC = 2.0
DEFAULT_MAX_SKEW_STD = 0.15
DEFAULT_SKEW_AGREE_TOLERANCE = 0.1
DEFAULT_MIN_AGREE_RATIO = 0.8


def _scan_snapshot(
    pool: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    spend_less_ok: bool | None = None,
) -> dict[str, Any]:
    bp = plan.get("brainiac_placement") or {}
    leader = bp.get("fee_model_leader") or {}
    return {
        "at": datetime.now(UTC).isoformat(),
        "spot": float((bp.get("quote_band_quote_per_base") or {}).get("spot") or pool.get("price") or 0),
        "liquidity_usd": float(pool.get("liquidity_usd") or 0),
        "fee_24h_usd": float(pool.get("fee_24h_usd") or pool.get("fee24h") or 0),
        "apr": pool.get("apr"),
        "skew": float(plan.get("skew") or bp.get("optimal_skew") or 0),
        "tick_lower_pct_below": float(plan.get("tick_lower_pct_below") or 0),
        "tick_upper_pct_above": float(plan.get("tick_upper_pct_above") or 0),
        "in_range_factor": float(bp.get("in_range_factor_at_skew") or 0),
        "theoretical_apr_pct": leader.get("theoretical_apr_pct"),
        "spend_less_ok": spend_less_ok,
    }


def run_pre_live_consensus(
    pool_id: str,
    *,
    deposit_usd: float,
    wide_width_pct: float = 80.0,
    min_in_range_factor: float = 0.55,
    scan_count: int = DEFAULT_SCAN_COUNT,
    scan_delay_sec: float = DEFAULT_SCAN_DELAY_SEC,
    max_skew_std: float = DEFAULT_MAX_SKEW_STD,
    skew_agree_tolerance: float = DEFAULT_SKEW_AGREE_TOLERANCE,
    min_agree_ratio: float = DEFAULT_MIN_AGREE_RATIO,
    run_spend_less_probe: bool = True,
    config: Any | None = None,
    fee_settings: Mapping[str, Any] | None = None,
    sol_price_usd: float = 180.0,
) -> dict[str, Any]:
    """Refresh pool + skew grid ``scan_count`` times; return consensus verdict + chosen plan."""

    n = max(0, int(scan_count))
    if n <= 0:
        return {"ok": True, "skipped": True, "reason": "scan_count=0"}

    from raydium_lp1.lp_brainiac_cursor_success import (
        build_brainiac_cursor_open_plan,
        fee_settings_for_brainiac_procedure,
        open_kwargs_from_plan,
        resolve_brainiac_live_auto_policy,
    )
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.raydium_clmm import wallet_balance
    from raydium_lp1.scanner import ScannerConfig, load_dotenv
    from raydium_lp1.spend_less_get_more import analyze_open_plan

    load_dotenv()
    sc = config if config is not None else ScannerConfig.from_file(
        __import__("pathlib").Path(__file__).resolve().parents[2] / "config" / "settings.json"
    )
    fee = dict(fee_settings or fee_settings_for_brainiac_procedure())
    auto = resolve_brainiac_live_auto_policy(deposit_usd, settings=fee)

    wb = wallet_balance()
    balance_sol = float(wb.get("sol_balance") or 0)
    pay_res = None

    scans: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    pools: list[dict[str, Any]] = []

    for idx in range(n):
        pool = fetch_pool_by_id(pool_id.strip(), config=sc)
        if pay_res is None:
            pay_res = resolve_pay_mint(pool, sc)
        plan = build_brainiac_cursor_open_plan(
            pool,
            pool.get("momentum"),
            default_width_pct=wide_width_pct,
            settings=fee,
            scanner=sc,
        )
        sl_ok: bool | None = None
        if run_spend_less_probe and pay_res is not None:
            kw = open_kwargs_from_plan(
                plan,
                deposit_usd=deposit_usd,
                band_tick_steps_cap=auto.band_tick_steps_cap,
            )
            pay_sym = str(pay_res.pay_symbol or "SOL").upper()
            sl = analyze_open_plan(
                requested_deposit_usd=float(deposit_usd),
                open_kwargs=kw,
                pay_symbol=pay_sym,
                balance_sol=balance_sol,
                reserve_sol=0.05,
                settings=fee,
                strategy_id="brainiac_cursor_success_80_skewed_no_escrow",
                sol_price_usd=sol_price_usd,
            )
            sl_ok = bool(sl.ok)
        snap = _scan_snapshot(pool, plan, spend_less_ok=sl_ok)
        snap["scan_index"] = idx + 1
        print(
            f"  scan {idx + 1}/{n}: skew={snap['skew']:.2f} "
            f"in_range={snap['in_range_factor']:.3f} "
            f"band {snap['tick_lower_pct_below']:.0f}/{snap['tick_upper_pct_above']:.0f}"
        )
        scans.append(snap)
        plans.append(dict(plan))
        pools.append(dict(pool))
        if idx < n - 1 and scan_delay_sec > 0:
            time.sleep(float(scan_delay_sec))

    skews = [float(s["skew"]) for s in scans]
    irs = [float(s["in_range_factor"]) for s in scans]
    median_skew = float(statistics.median(skews))
    skew_std = float(statistics.pstdev(skews)) if len(skews) > 1 else 0.0
    min_ir = min(irs) if irs else 0.0
    max_ir = max(irs) if irs else 0.0
    median_ir = float(statistics.median(irs)) if irs else 0.0

    agree_count = sum(1 for sk in skews if abs(sk - median_skew) <= skew_agree_tolerance)
    agree_ratio = agree_count / len(scans) if scans else 0.0

    best_idx = min(range(len(skews)), key=lambda i: abs(skews[i] - median_skew))
    chosen_plan = plans[best_idx]
    chosen_pool = pools[best_idx]
    chosen_scan = scans[best_idx]

    block_reasons: list[str] = []
    if skew_std > max_skew_std:
        block_reasons.append(
            f"skew unstable: std {skew_std:.3f} > max {max_skew_std:.3f} "
            f"(skews={[round(s, 2) for s in skews]})"
        )
    if min_ir < min_in_range_factor:
        block_reasons.append(
            f"min in_range_factor {min_ir:.3f} < {min_in_range_factor:.3f} across scans"
        )
    if agree_ratio < min_agree_ratio:
        block_reasons.append(
            f"skew agreement {agree_count}/{len(scans)} ({agree_ratio:.0%}) "
            f"< {min_agree_ratio:.0%} (median skew {median_skew:.2f})"
        )
    if run_spend_less_probe and any(s.get("spend_less_ok") is False for s in scans):
        bad = [s["scan_index"] for s in scans if s.get("spend_less_ok") is False]
        block_reasons.append(f"SPEND LESS blocked on scan(s) {bad}")

    ok = not block_reasons
    recommendation = (
        f"Consensus OK: median skew {median_skew:.2f}, in-range {median_ir:.2f} "
        f"({agree_count}/{len(scans)} scans agree)."
        if ok
        else "LIVE blocked — " + "; ".join(block_reasons)
    )

    return {
        "ok": ok,
        "skipped": False,
        "scan_count": n,
        "scan_delay_sec": scan_delay_sec,
        "scans": scans,
        "median_skew": round(median_skew, 4),
        "skew_std": round(skew_std, 4),
        "min_in_range_factor": round(min_ir, 4),
        "max_in_range_factor": round(max_ir, 4),
        "median_in_range_factor": round(median_ir, 4),
        "agree_count": agree_count,
        "agree_ratio": round(agree_ratio, 4),
        "max_skew_std": max_skew_std,
        "min_agree_ratio": min_agree_ratio,
        "chosen_scan_index": best_idx + 1,
        "chosen_placement": {
            "skew": chosen_scan.get("skew"),
            "tick_lower_pct_below": chosen_scan.get("tick_lower_pct_below"),
            "tick_upper_pct_above": chosen_scan.get("tick_upper_pct_above"),
            "in_range_factor": chosen_scan.get("in_range_factor"),
            "theoretical_apr_pct": chosen_scan.get("theoretical_apr_pct"),
        },
        "chosen_plan": chosen_plan,
        "chosen_pool": chosen_pool,
        "block_reasons": block_reasons,
        "recommendation": recommendation,
    }
