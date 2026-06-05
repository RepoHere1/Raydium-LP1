"""Aggregate LIVE CLMM opens by LP style for dashboard dial-in."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from raydium_lp1.lp_full_range import clmm_position_in_range


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        s = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _position_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    clmm = row.get("clmm_result") if isinstance(row.get("clmm_result"), dict) else {}
    opened = _parse_ts(row.get("opened_at"))
    age_h = None
    if opened:
        age_h = round((datetime.now(UTC) - opened).total_seconds() / 3600.0, 2)
    in_range = clmm_position_in_range(row, clmm) if clmm else None
    fees = row.get("fees_collected_usd")
    try:
        fees_f = float(fees) if fees is not None else 0.0
    except (TypeError, ValueError):
        fees_f = 0.0
    return {
        "pair": row.get("pair"),
        "pool_id": row.get("pool_id"),
        "lp_style_key": row.get("lp_style_key") or "unknown",
        "lp_style_label": row.get("lp_style_label") or "unknown",
        "lp_strategy_id": row.get("lp_strategy_id"),
        "lp_placement": row.get("lp_placement"),
        "apr_at_open": row.get("apr"),
        "input_amount_sol": row.get("input_amount_sol"),
        "fees_collected_usd": fees_f,
        "in_range_at_open": in_range,
        "out_of_range_at_open": in_range is False,
        "age_hours": age_h,
        "position_nft_mint": row.get("position_nft_mint"),
    }


def build_live_style_report(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize open LIVE positions grouped by ``lp_style_key``."""

    metrics = [_position_metrics(p) for p in positions if isinstance(p, dict)]
    by_key: dict[str, list[dict[str, Any]]] = {}
    for m in metrics:
        by_key.setdefault(str(m["lp_style_key"]), []).append(m)

    groups: list[dict[str, Any]] = []
    for key, rows in sorted(by_key.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = len(rows)
        apr_vals = [float(r["apr_at_open"]) for r in rows if r.get("apr_at_open") is not None]
        fees = sum(float(r.get("fees_collected_usd") or 0) for r in rows)
        oor = sum(1 for r in rows if r.get("out_of_range_at_open"))
        in_rng = sum(1 for r in rows if r.get("in_range_at_open") is True)
        groups.append(
            {
                "lp_style_key": key,
                "lp_style_label": rows[0].get("lp_style_label") if rows else key,
                "count": n,
                "avg_apr_at_open": round(sum(apr_vals) / len(apr_vals), 2) if apr_vals else None,
                "total_fees_usd": round(fees, 4),
                "in_range_at_open": in_rng,
                "out_of_range_at_open": oor,
                "positions": rows,
            }
        )

    recommendation = _recommendation(groups, len(metrics))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "open_count": len(metrics),
        "style_groups": groups,
        "recommendation": recommendation,
        "notes": [
            "Metrics use data at open (tick vs band). Re-run scan or add RPC refresh for live in-range status.",
            "Compare styles after 3+ opens per style; fees require claim/decrease to appear on-chain.",
        ],
    }


def _recommendation(groups: list[dict[str, Any]], total: int) -> str:
    if total == 0:
        return "No LIVE opens yet — arm LIVE and open a position to start style tracking."
    if total < 2:
        return "Only one LIVE open — change lp_active_strategy in settings before the next open to A/B test."
    best = None
    best_score = -1.0
    for g in groups:
        n = int(g.get("count") or 0)
        if n < 1:
            continue
        in_r = int(g.get("in_range_at_open") or 0)
        fees = float(g.get("total_fees_usd") or 0)
        apr = float(g.get("avg_apr_at_open") or 0)
        score = fees * 10.0 + in_r * 2.0 - int(g.get("out_of_range_at_open") or 0) * 1.5 + min(apr, 500) / 100.0
        if score > best_score:
            best_score = score
            best = g
    if best:
        return (
            f"Early leader: {best.get('lp_style_label')} "
            f"({best.get('count')} open(s), in-range@open={best.get('in_range_at_open')}, "
            f"fees=${best.get('total_fees_usd'):.2f}). "
            "Not statistically significant until you have several closes per style."
        )
    return "Log more opens per style to compare fee capture vs out-of-range rate."
