"""Paper fee estimates for open LP positions (demo + live display)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        t = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def hours_since_open(opened_at: str | None) -> float:
    start = _parse_iso(opened_at)
    if not start:
        return 6.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - start
    return max(0.25, min(168.0, delta.total_seconds() / 3600.0))


def estimate_lp_fees_usd(
    pool: Mapping[str, Any],
    *,
    position_size_sol: float,
    sol_usd: float = 150.0,
    fee_bps: float = 25.0,
    hours_open: float = 6.0,
    in_range_factor: float = 0.65,
    width_pct: float = 20.0,
) -> float:
    """Heuristic fees from 24h volume × liquidity share × time in range."""

    vol = float(pool.get("volume_24h_usd") or pool.get("volume24h") or 0)
    tvl = float(pool.get("liquidity_usd") or pool.get("tvl") or 0)
    if vol <= 0 or tvl <= 0:
        return 0.0
    pos_usd = max(0.0, float(position_size_sol)) * sol_usd
    share = min(0.2, pos_usd / tvl)
    tight_bonus = 1.15 if width_pct <= 15 else 1.0
    pool_fees_day = vol * (fee_bps / 10_000.0)
    return pool_fees_day * share * in_range_factor * tight_bonus * (hours_open / 24.0)


def attach_fees_to_position(
    row: dict[str, Any],
    pool: Mapping[str, Any],
    *,
    position_size_sol: float,
    fee_bps: float,
    sol_usd: float = 150.0,
) -> dict[str, Any]:
    width = float(row.get("width_pct") or pool.get("lp_width_pct") or 20.0)
    hours = hours_since_open(str(row.get("opened_at") or ""))
    fees = estimate_lp_fees_usd(
        pool,
        position_size_sol=position_size_sol,
        sol_usd=sol_usd,
        fee_bps=fee_bps,
        hours_open=hours,
        width_pct=width,
    )
    out = dict(row)
    out["fees_collected_usd"] = round(fees, 4)
    out["fees_hours_basis"] = round(hours, 2)
    return out


def sum_open_fees_usd(rows: list[dict[str, Any]]) -> float:
    return round(sum(float(r.get("fees_collected_usd") or 0) for r in rows), 4)
