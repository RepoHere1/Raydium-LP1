"""CLMM wide-band (max 80% width) helpers — not literal min/max pool ticks.

Literal 100% full range (pool MIN_TICK..MAX_TICK) is disabled for live opens:
it forces expensive tick-array rent (~0.15 SOL) on small deposits. The
``standard_full_range`` strategy uses a centered wide band (default 80% total width).
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from raydium_lp1.lp_order_strategies import STRATEGY_FULL_RANGE

# Raydium CLMM constants (for detecting legacy literal positions only)
MIN_TICK = -443636
MAX_TICK = 443636

# Live opens: never exceed this total band width (% of spot, centered)
MAX_WIDE_BAND_WIDTH_PCT = 80.0
DEFAULT_WIDE_BAND_WIDTH_PCT = 80.0
WIDE_BAND_PLACEMENT = "wide_band"


def tick_bounds_for_spacing(tick_spacing: int) -> tuple[int, int]:
    """Aligned min/max ticks (legacy literal full range — not used for new opens)."""

    ts = max(1, int(tick_spacing or 1))
    lo = int(math.ceil(MIN_TICK / ts) * ts)
    hi = int(math.floor(MAX_TICK / ts) * ts)
    return lo, hi


def clamp_wide_width_pct(width_pct: float | None) -> float:
    w = float(width_pct if width_pct is not None else DEFAULT_WIDE_BAND_WIDTH_PCT)
    return max(10.0, min(MAX_WIDE_BAND_WIDTH_PCT, w))


def wide_band_half_pct(width_pct: float | None = None) -> float:
    """Each side of spot for a centered band (total width = 2 * half)."""

    return clamp_wide_width_pct(width_pct) / 2.0


def is_wide_band_strategy_id(strategy_id: str) -> bool:
    return (strategy_id or "").strip().lower() == STRATEGY_FULL_RANGE


def is_wide_band_open_kwargs(open_kwargs: Mapping[str, Any] | None) -> bool:
    if not open_kwargs:
        return False
    if open_kwargs.get("wide_range"):
        return True
    if open_kwargs.get("full_range") and not open_kwargs.get("literal_pool_full_range"):
        return True
    return False


def is_wide_band_position(row: Mapping[str, Any]) -> bool:
    placement = str(row.get("lp_placement") or "")
    if placement in (WIDE_BAND_PLACEMENT, "full_range"):
        return True
    if is_wide_band_strategy_id(str(row.get("lp_strategy_id") or "")):
        return True
    clmm = row.get("clmm_result") if isinstance(row.get("clmm_result"), dict) else {}
    return bool(clmm.get("wide_range")) or bool(clmm.get("full_range"))


# Back-compat aliases
is_full_range_strategy_id = is_wide_band_strategy_id
is_full_range_open_kwargs = is_wide_band_open_kwargs
is_full_range_position = is_wide_band_position


def position_spans_full_ticks(clmm: Mapping[str, Any], *, min_fraction: float = 0.85) -> bool:
    """True if position used legacy literal pool min/max ticks."""

    lo = clmm.get("tick_lower")
    hi = clmm.get("tick_upper")
    if lo is None or hi is None:
        return False
    spacing = int(clmm.get("tick_spacing") or 1)
    min_lo, max_hi = tick_bounds_for_spacing(spacing)
    span = max_hi - min_lo
    if span <= 0:
        return False
    try:
        covered = int(hi) - int(lo)
    except (TypeError, ValueError):
        return False
    return covered >= span * min_fraction


def clmm_position_in_range(row: Mapping[str, Any], clmm: Mapping[str, Any]) -> bool | None:
    """Whether spot tick is inside the position band.

    Wide-band positions can go out of range when price moves beyond ~40% from center.
    Legacy literal min/max positions are treated as always in range.
    """

    if position_spans_full_ticks(clmm):
        return True
    lo = clmm.get("tick_lower")
    hi = clmm.get("tick_upper")
    cur = clmm.get("tick_current")
    if lo is None or hi is None or cur is None:
        return None
    try:
        return int(lo) <= int(cur) <= int(hi)
    except (TypeError, ValueError):
        return None


def open_kwargs_for_wide_band(*, width_pct: float | None = None) -> dict[str, Any]:
    w = clamp_wide_width_pct(width_pct)
    half = w / 2.0
    return {
        "single_side": None,
        "wide_range": True,
        "full_range": False,
        "literal_pool_full_range": False,
        "wide_range_width_pct": w,
        "tick_lower_pct_below": half,
        "tick_upper_pct_above": half,
        "band_tick_steps": max(8, int(round(6 + w * 0.45))),
        "slippage_bps": 2500,
    }
