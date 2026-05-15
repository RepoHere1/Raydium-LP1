"""Post-scan diagnosis: turn rejection mass + current thresholds into tuning hints.

This module is **not** a price oracle or a guarantee of profit. It applies one
documented *objective bias* — prefer very high reported APR while keeping
defensible routes back to base (SOL / stable quotes) and liquidity floors —
then maps ``rejection_breakdown`` categories to concrete ``settings.json``
levers and risk labels so you can iterate quickly without guessing.
"""

from __future__ import annotations

import math
import sys
from typing import Any, TextIO

from raydium_lp1 import strategies, verdicts


OBJECTIVE_BIAS_ID = "high_apr_exit_to_base"
OBJECTIVE_BIAS_SUMMARY = (
    "Bias: favor pools with extreme reported APR *and* evidence you can unwind "
    "to SOL/USDC/USDT; deprioritize obvious dust TVL, missing routes, and "
    "unsafe Jupiter price impact relative to your caps."
)


def _pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * float(count) / float(total), 2)


def _nice_floor(x: float, floor: float) -> float:
    if x <= floor or not math.isfinite(x):
        return floor
    return float(max(floor, round(x, 2)))


def _dominant_drivers(breakdown: dict[str, int], rejected: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if rejected <= 0 or not breakdown:
        return rows
    for cat, n in sorted(breakdown.items(), key=lambda kv: -kv[1])[:6]:
        rows.append(
            {
                "category": cat,
                "count": int(n),
                "pct_of_rejects": _pct(int(n), rejected),
            }
        )
    return rows


def _coherence_notes(config: Any) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    if config.hard_exit_min_tvl_usd > 0 and config.min_liquidity_usd > 0:
        if config.hard_exit_min_tvl_usd > config.min_liquidity_usd:
            notes.append(
                {
                    "id": "hard_exit_stricter_than_min_liquidity",
                    "ok": False,
                    "detail": (
                        f"hard_exit_min_tvl_usd ({config.hard_exit_min_tvl_usd:.2f}) is above "
                        f"min_liquidity_usd ({config.min_liquidity_usd:.2f}). Pools in the gap "
                        "fail the HARD exit line before softer TVL messaging; align the two if "
                        "that was unintentional."
                    ),
                }
            )
        elif config.hard_exit_min_tvl_usd < config.min_liquidity_usd * 0.25:
            notes.append(
                {
                    "id": "hard_exit_far_below_min_liquidity",
                    "ok": True,
                    "detail": (
                        f"hard_exit_min_tvl_usd ({config.hard_exit_min_tvl_usd:.2f}) is much lower "
                        f"than min_liquidity_usd ({config.min_liquidity_usd:.2f}). The Raydium filter "
                        "already enforces a higher TVL floor; the hard line mostly guards sketch exits."
                    ),
                }
            )
    if config.max_route_price_impact_pct > 30.0:
        notes.append(
            {
                "id": "impact_cap_above_30",
                "ok": False,
                "detail": (
                    f"max_route_price_impact_pct is {config.max_route_price_impact_pct:.2f}. "
                    "Values above 30% are inconsistent with the stated emergency slippage cap; "
                    "clamp to 30 unless you intentionally accept worse execution."
                ),
            }
        )
    return notes


def _wallet_wall(report: dict[str, Any]) -> dict[str, Any] | None:
    cap = report.get("wallet_capacity") or {}
    inner = cap.get("capacity") or {}
    pre = int(report.get("candidate_count_pre_capacity") or 0)
    post = int(report.get("candidate_count") or 0)
    mx = inner.get("max_positions")
    if mx is None:
        return None
    try:
        mx_i = int(mx)
    except (TypeError, ValueError):
        return None
    if mx_i <= 0 and (pre > 0 or post == 0):
        return {
            "max_positions": mx_i,
            "candidate_count_pre_capacity": pre,
            "candidate_count_after_cap": post,
            "balance_sol": (cap.get("balance") or {}).get("sol"),
            "position_size_sol": inner.get("position_size_sol"),
            "reserved_sol": inner.get("reserved_sol"),
        }
    if pre > post > 0:
        return {
            "max_positions": mx_i,
            "candidate_count_pre_capacity": pre,
            "candidate_count_after_cap": post,
            "balance_sol": (cap.get("balance") or {}).get("sol"),
            "position_size_sol": inner.get("position_size_sol"),
            "reserved_sol": inner.get("reserved_sol"),
        }
    return None


def _setting_pressure(
    config: Any,
    breakdown: dict[str, int],
    rejected: int,
) -> list[dict[str, Any]]:
    if rejected <= 0:
        return []
    pressures: list[dict[str, Any]] = []
    ranked = sorted(breakdown.items(), key=lambda kv: -kv[1])

    def add(
        *,
        setting_key: str,
        direction: str,
        rationale: str,
        risk_if_changed: str,
        concrete: str | None = None,
        min_share: float = 8.0,
        category: str,
        count: int,
    ) -> None:
        share = _pct(count, rejected)
        if share < min_share:
            return
        row: dict[str, Any] = {
            "category_driver": category,
            "reject_share_pct": share,
            "setting_key": setting_key,
            "direction": direction,
            "rationale": rationale,
            "risk_if_changed": risk_if_changed,
        }
        if concrete:
            row["concrete_suggestion"] = concrete
        pressures.append(row)

    for cat, n in ranked:
        if n <= 0:
            continue
        if cat == "tvl_below_threshold":
            cur = config.min_liquidity_usd
            nxt = _nice_floor(cur * 0.55, 25.0)
            if nxt < cur:
                add(
                    category=cat,
                    count=n,
                    setting_key="min_liquidity_usd",
                    direction="lower",
                    rationale="Large share of rejects cite TVL below your Raydium floor.",
                    risk_if_changed="medium",
                    concrete=f"try stepping min_liquidity_usd toward {nxt:.0f} (was {cur:.0f}); thinner books = harder exits.",
                    min_share=10.0,
                )
        elif cat == "apr_below_threshold":
            cur = config.min_apr
            nxt = _nice_floor(cur * 0.65, 50.0)
            if nxt < cur:
                preset = strategies.STRATEGY_PRESETS.get(strategies.STRATEGY_DEGEN)
                hint = ""
                if preset:
                    hint = f" degen preset floor is {preset.min_apr:.0f}% APR if you want a packaged baseline."
                add(
                    category=cat,
                    count=n,
                    setting_key="min_apr",
                    direction="lower",
                    rationale="Many pools fail the APR gate before any route check.",
                    risk_if_changed="low",
                    concrete=f"try min_apr near {nxt:.0f} (was {cur:.0f}); or set strategy to degen.{hint}",
                    min_share=10.0,
                )
        elif cat == "volume_below_threshold":
            cur = config.min_volume_24h_usd
            nxt = _nice_floor(cur * 0.5, 10.0)
            if nxt < cur:
                add(
                    category=cat,
                    count=n,
                    setting_key="min_volume_24h_usd",
                    direction="lower",
                    rationale="24h volume gate is blocking a large fraction of scanned pools.",
                    risk_if_changed="medium",
                    concrete=f"try min_volume_24h_usd near {nxt:.0f} (was {cur:.0f}); dead tape hides rug risk.",
                    min_share=8.0,
                )
        elif cat == "hard_exit_red_line":
            cur = config.hard_exit_min_tvl_usd
            nxt = _nice_floor(cur * 0.7, 0.0)
            if cur > 0 and nxt < cur:
                add(
                    category=cat,
                    count=n,
                    setting_key="hard_exit_min_tvl_usd",
                    direction="lower",
                    rationale="HARD TVL exit line is rejecting many pools you might otherwise watch.",
                    risk_if_changed="high",
                    concrete=f"try hard_exit_min_tvl_usd near {nxt:.0f} (was {cur:.0f}) or align with min_liquidity_usd.",
                    min_share=5.0,
                )
        elif cat == "price_impact_too_high":
            cur = config.max_route_price_impact_pct
            if cur < 30.0:
                nxt = min(30.0, round(cur + 5.0, 1))
                add(
                    category=cat,
                    count=n,
                    setting_key="max_route_price_impact_pct",
                    direction="raise",
                    rationale="Jupiter quotes show impact above your cap — exits would be expensive.",
                    risk_if_changed="high",
                    concrete=f"cautiously raise max_route_price_impact_pct toward {nxt:.1f} (was {cur:.1f}); hard ceiling 30.",
                    min_share=5.0,
                )
        elif cat == "no_sell_route":
            add(
                category=cat,
                count=n,
                setting_key="require_sell_route",
                direction="lower",
                rationale="Many pools fail aggregated sell-route probes.",
                risk_if_changed="critical",
                concrete='set "require_sell_route": false only if you accept illiquid meme inventory.',
                min_share=5.0,
            )
        elif cat == "quote_symbol_not_allowed":
            add(
                category=cat,
                count=n,
                setting_key="allowed_quote_symbols",
                direction="widen",
                rationale="Pairs lack SOL/USDC/USDT on the mint metadata Raydium exposes.",
                risk_if_changed="high",
                concrete="expand allowed_quote_symbols only for quotes you will really exit through.",
                min_share=5.0,
            )
        elif cat == "pool_age":
            add(
                category=cat,
                count=n,
                setting_key="max_pool_age_hours / min_pool_age_hours",
                direction="relax",
                rationale="Age window is excluding many pools.",
                risk_if_changed="medium",
                concrete="widen max_pool_age_hours or lower min_pool_age_hours depending on which side fires.",
                min_share=5.0,
            )
        elif cat == "lp_burn_too_low":
            add(
                category=cat,
                count=n,
                setting_key="min_burn_percent",
                direction="lower",
                rationale="LP burn requirement is blocking a measurable slice.",
                risk_if_changed="medium",
                concrete="lower min_burn_percent toward Raydium-reported reality for sketch pairs.",
                min_share=5.0,
            )
        elif cat == "blocked_list":
            add(
                category=cat,
                count=n,
                setting_key="blocked_token_symbols / blocked_mints",
                direction="review",
                rationale="Your explicit block lists are doing work.",
                risk_if_changed="low",
                concrete="trim block lists only for symbols you are willing to trade again.",
                min_share=5.0,
            )

    return pressures


def _narrative_lines(
    config: Any,
    report: dict[str, Any],
    drivers: list[dict[str, Any]],
    pressures: list[dict[str, Any]],
    coherence: list[dict[str, Any]],
    wallet_hit: dict[str, Any] | None,
) -> list[str]:
    lines: list[str] = []
    lines.append(OBJECTIVE_BIAS_SUMMARY)
    if report.get("notice"):
        lines.append(f"Notice: {report['notice']}")
    scanned = int(report.get("scanned_count") or 0)
    cand = int(report.get("candidate_count") or 0)
    rej = int(report.get("rejected_count") or 0)
    lines.append(
        f"Cycle: scanned={scanned} candidates={cand} rejected={rej} "
        f"(strategy={config.strategy!r}, require_sell_route={config.require_sell_route})."
    )
    if wallet_hit and int(wallet_hit.get("max_positions") or 0) <= 0:
        lines.append(
            "Wallet capacity wall: max_positions=0 — fund SOL or lower position_size_sol / "
            "reserve_sol before any pool can become an actionable slot."
        )
    elif wallet_hit and int(wallet_hit.get("candidate_count_pre_capacity") or 0) > int(
        wallet_hit.get("candidate_count_after_cap") or 0
    ):
        lines.append(
            f"Capacity trim: {wallet_hit['candidate_count_pre_capacity']} pre-cap candidates -> "
            f"{wallet_hit['candidate_count_after_cap']} after max_positions={wallet_hit['max_positions']}."
        )
    if drivers:
        top = drivers[0]
        lines.append(
            f"Largest reject driver: {top['category']} ({top['pct_of_rejects']:.1f}% of rejects, n={top['count']})."
        )
        if len(drivers) > 1:
            tail = ", ".join(f"{d['category']} {_pct(d['count'], rej):.1f}%" for d in drivers[1:3])
            if tail:
                lines.append(f"Next signals: {tail}.")
    if pressures:
        lines.append("Actionable levers (machine list repeats below with risk tags):")
        for p in pressures[:4]:
            lines.append(
                f"  - {p['setting_key']} ({p['direction']}, risk={p['risk_if_changed']}): "
                f"{p.get('concrete_suggestion') or p['rationale']}"
            )
    else:
        lines.append(
            "No dominant category cleared the heuristic threshold; inspect rejection_reason_histogram "
            "or export CSV for long-tail reasons."
        )
    for note in coherence:
        if not note.get("ok", True):
            lines.append(f"Coherence: {note['id']} — {note['detail']}")
    if cand > 0:
        lines.append(
            f"{cand} candidate(s) passed this pass — keep health + route telemetry on; "
            "tighten, do not loosen, if warnings pile up."
        )
    else:
        lines.append(
            "Zero candidates: move one gate at a time, re-run, and compare breakdown deltas "
            "so you know which lever actually moved the funnel."
        )
    return lines


def build_scan_diagnosis(config: Any, report: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable diagnosis dict (also embedded in ``--write-reports`` JSON)."""

    scanned = int(report.get("scanned_count") or 0)
    cand = int(report.get("candidate_count") or 0)
    rej = int(report.get("rejected_count") or 0)
    bd = {str(k): int(v) for k, v in (report.get("rejection_breakdown") or {}).items()}
    hist = report.get("rejection_reason_histogram") or {}
    top_strings = list(hist.items())[:5] if isinstance(hist, dict) else []

    drivers = _dominant_drivers(bd, rej)
    pressures = _setting_pressure(config, bd, rej)
    coherence = _coherence_notes(config)
    wallet_hit = _wallet_wall(report)

    top_pct = drivers[0]["pct_of_rejects"] if drivers else 0.0
    bottleneck = "unknown"
    if rej <= 0:
        bottleneck = "no_rejects"
    elif top_pct >= 65.0:
        bottleneck = "single_dominant_gate"
    elif top_pct >= 35.0:
        bottleneck = "split_top_gate"
    else:
        bottleneck = "fragmented_many_reasons"

    signal = "idle"
    if scanned <= 0:
        signal = "no_scan_data"
    elif cand > 0:
        signal = "candidates_present"
    elif rej > 0:
        signal = "all_rejected"

    return {
        "version": 1,
        "objective_bias_id": OBJECTIVE_BIAS_ID,
        "objective_bias_summary": OBJECTIVE_BIAS_SUMMARY,
        "bottleneck_shape": bottleneck,
        "scan_signal": signal,
        "scan_summary": {
            "scanned": scanned,
            "candidates": cand,
            "rejected": rej,
            "pass_rate_pct": _pct(cand, max(1, cand + rej)),
        },
        "dominant_reject_drivers": drivers,
        "setting_pressure": pressures,
        "coherence_checks": coherence,
        "wallet_capacity_signal": wallet_hit,
        "top_exact_first_reasons_sample": [{"reason": r, "count": int(n)} for r, n in top_strings],
        "narrative_lines": _narrative_lines(config, report, drivers, pressures, coherence, wallet_hit),
    }


def print_scan_diagnosis(
    diagnosis: dict[str, Any],
    *,
    stream_cfg: verdicts.StreamConfig | None = None,
    file: TextIO | None = None,
) -> None:
    """Pretty-print diagnosis to stderr (and optional verdict mirror log)."""

    out: TextIO = file or sys.stderr
    lines: list[str] = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("[objective-engine] post-scan diagnosis (rules + counts, not a market oracle)")
    lines.append(f"Objective bias: {diagnosis.get('objective_bias_id', OBJECTIVE_BIAS_ID)}")
    lines.append(
        f"Shape: bottleneck={diagnosis.get('bottleneck_shape')} | signal={diagnosis.get('scan_signal')}"
    )
    summary = diagnosis.get("scan_summary") or {}
    lines.append(
        f"Summary: scanned={summary.get('scanned')} candidates={summary.get('candidates')} "
        f"rejected={summary.get('rejected')} (pass_rate {summary.get('pass_rate_pct')}%)"
    )
    for row in diagnosis.get("narrative_lines") or []:
        lines.append(f"  {row}")
    pressures = diagnosis.get("setting_pressure") or []
    if pressures:
        lines.append("Setting pressure (sorted by reject share):")
        for p in pressures:
            share = p.get("reject_share_pct")
            tail = p.get("concrete_suggestion") or p.get("rationale", "")
            lines.append(
                f"  - [{p.get('category_driver')}] ~{share}% rejects -> {p.get('setting_key')} "
                f"{p.get('direction')} [risk={p.get('risk_if_changed')}] {tail}"
            )
    lines.append("=" * 72)
    block = "\n".join(lines) + "\n"
    print(block, file=out, end="", flush=True)
    if stream_cfg is not None and stream_cfg.verdict_log_path:
        verdicts.append_verdict_log_plain(stream_cfg, block)
