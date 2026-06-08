"""CLMM / concentrated LP opening strategies (paper + live-ready plans).

Official-style strategy IDs aligned with Raydium concentrated liquidity (CLMM) practice.
Each strategy returns a JSON plan usable in demo simulation and live execution hooks.

**Permanent NO ESCROW PAID** (`no_escrow_policy`): every strategy blocks sunk tick-array rent
(~0.072 SOL per new array). Recoverable position NFT rent (~0.008 SOL) is required and returned on close.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from raydium_lp1 import lp_range_planner

STRATEGY_CENTERED_TIGHT = "centered_tight_range"
STRATEGY_ASYMMETRIC = "asymmetric_single_asset"
STRATEGY_ATR_WIDTH = "volatility_atr_width"
STRATEGY_TRAILING_SKEW = "trailing_dynamic_skew"
STRATEGY_FULL_RANGE = "standard_full_range"
STRATEGY_AUTO = "auto_volatility_pick"
STRATEGY_BRAINIAC_CURSOR_SUCCESS = "brainiac_cursor_success_80_skewed_no_escrow"

ALL_STRATEGY_IDS: tuple[str, ...] = (
    STRATEGY_AUTO,
    STRATEGY_CENTERED_TIGHT,
    STRATEGY_ASYMMETRIC,
    STRATEGY_ATR_WIDTH,
    STRATEGY_TRAILING_SKEW,
    STRATEGY_FULL_RANGE,
    STRATEGY_BRAINIAC_CURSOR_SUCCESS,
)


@dataclass(frozen=True)
class LPStrategySpec:
    id: str
    official_name: str
    short_label: str
    description: str
    raydium_notes: str


STRATEGY_CATALOG: tuple[LPStrategySpec, ...] = (
    LPStrategySpec(
        id=STRATEGY_CENTERED_TIGHT,
        official_name="Centered Tight Range Order",
        short_label="Centered tight",
        description=(
            "Deploys a narrow spread symmetric around the current spot price. Maximizes fee "
            "accumulation when price chops inside the band; needs frequent re-centering if spot drifts."
        ),
        raydium_notes="CLMM concentrated position with lower/upper ticks hugging spot (Raydium CLMM openPosition).",
    ),
    LPStrategySpec(
        id=STRATEGY_ASYMMETRIC,
        official_name="Asymmetric Single-Asset Range Order",
        short_label="Asymmetric one-sided",
        description=(
            "Places liquidity entirely above or below spot (e.g. $95–$100 when spot is $100). Acts like "
            "a dynamic limit ladder: bullish = band above spot (sell into strength); bearish = band below (buy dips)."
        ),
        raydium_notes="Single-sided deposit bias; common for DCA / inventory skew on CLMM.",
    ),
    LPStrategySpec(
        id=STRATEGY_ATR_WIDTH,
        official_name="Volatility-Weighted Width Order",
        short_label="ATR width",
        description=(
            "Scales band width from recent day min/max swing (ATR proxy on Raydium list data). "
            "Wider in high vol, tighter in quiet markets."
        ),
        raydium_notes="Tick span widens with realized volatility before openPosition.",
    ),
    LPStrategySpec(
        id=STRATEGY_TRAILING_SKEW,
        official_name="Trailing / Dynamic Skew Order",
        short_label="Trailing skew",
        description=(
            "Shifts the whole band toward momentum inflow bias so liquidity stays near the moving "
            "price — similar to AMM grid / market-making skew."
        ),
        raydium_notes="Recenters band on spot each rebalance; pairs with momentum detective inflow_bias.",
    ),
    LPStrategySpec(
        id=STRATEGY_FULL_RANGE,
        official_name="Standard Wide Band Order (max 80%)",
        short_label="Wide band",
        description=(
            "Centered CLMM band up to 80% total width around spot (not literal pool min/max ticks). "
            "Much lower SOL rent than true full range; price can go out of range on large moves."
        ),
        raydium_notes=(
            "CLMM openPosition with ±40% price band (80% total). Literal MIN/MAX ticks are disabled for live opens."
        ),
    ),
    LPStrategySpec(
        id=STRATEGY_AUTO,
        official_name="Auto (volatility pick)",
        short_label="Auto",
        description=(
            "Picks centered tight vs ATR width from pool churn and day-range swing. Good default until "
            "you specialize per pair."
        ),
        raydium_notes="Uses scanner lp_range_mode=auto width selection.",
    ),
    LPStrategySpec(
        id=STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        official_name="BRAINIAC-CURSOR-SUCCESS-80%-SKEWED-WIDE-No ESCROW",
        short_label="Brainiac 80% skew",
        description=(
            "Reasoning-based 80% skewed straddle: Brainiac scores pool, grid-searches skew for "
            "24h overlap, two-sided wallet inventory, pay-type-only settlement, recoverable rent."
        ),
        raydium_notes=(
            "Placement: SUPER-BRAINIAC skew on 80% width; no pay-only wide fallback. "
            "Settlement: sweeps and funding use resolve_pay_mint only; non-pay pair token never "
            "sink or swap input. Rent: recoverable NFT, no sunk tick-array escrow."
        ),
    ),
)


def catalog_dict() -> list[dict[str, str]]:
    return [
        {
            "id": s.id,
            "official_name": s.official_name,
            "short_label": s.short_label,
            "description": s.description,
            "raydium_notes": s.raydium_notes,
        }
        for s in STRATEGY_CATALOG
    ]


def get_strategy(strategy_id: str) -> LPStrategySpec | None:
    sid = (strategy_id or STRATEGY_AUTO).strip().lower()
    for s in STRATEGY_CATALOG:
        if s.id == sid:
            return s
    return None


def _atr_width_pct(pool: Mapping[str, Any], default_pct: float) -> float:
    raw = pool.get("raw") if isinstance(pool.get("raw"), dict) else {}
    day = raw.get("day") if isinstance(raw.get("day"), dict) else {}
    pmin = float(day.get("priceMin") or 0)
    pmax = float(day.get("priceMax") or 0)
    if pmin > 0 and pmax > pmin:
        swing = (pmax - pmin) / pmin * 100.0
        return max(8.0, min(55.0, max(default_pct, swing * 0.85)))
    return default_pct


def execute_asymmetric_order(
    spot_price: float,
    *,
    order_type: str = "bullish",
    width_pct: float = 5.0,
) -> dict[str, float]:
    """Single-asset range above (bullish) or below (bearish) spot."""

    w = width_pct / 100.0
    if order_type.lower() in ("bullish", "above", "sell"):
        return {"lower": spot_price, "upper": spot_price * (1.0 + w)}
    return {"lower": spot_price * (1.0 - w), "upper": spot_price}


def build_open_order(
    pool: Mapping[str, Any],
    momentum: Mapping[str, Any] | None,
    *,
    strategy_id: str,
    default_width_pct: float = 20.0,
    skew_use_momentum: bool = True,
) -> dict[str, Any]:
    """Build a strategy plan for demo or live (paper execution metadata included)."""

    spec = get_strategy(strategy_id) or get_strategy(STRATEGY_AUTO)
    assert spec is not None
    sid = spec.id
    spot, spot_src = lp_range_planner.spot_price_quote_per_base(pool)
    skew, skew_notes = lp_range_planner.momentum_skew(momentum, use_momentum=skew_use_momentum)

    if sid == STRATEGY_AUTO:
        width_pct, width_note = lp_range_planner.pick_width_pct(
            pool,
            momentum,
            candidates=(12.0, 20.0, 30.0, 50.0),
            default_pct=default_width_pct,
            mode="auto",
            risk_profile="balanced",
        )
        sid = STRATEGY_CENTERED_TIGHT if width_pct <= 22 else STRATEGY_ATR_WIDTH
        spec = get_strategy(sid) or spec
    elif sid == STRATEGY_ATR_WIDTH:
        width_pct = _atr_width_pct(pool, default_width_pct)
        width_note = f"atr_proxy:{width_pct:.1f}%"
    elif sid == STRATEGY_CENTERED_TIGHT:
        width_pct = min(default_width_pct, 15.0)
        width_note = "centered_tight_cap"
        skew = 0.0
    elif sid == STRATEGY_FULL_RANGE:
        from raydium_lp1.lp_full_range import DEFAULT_WIDE_BAND_WIDTH_PCT

        width_pct = DEFAULT_WIDE_BAND_WIDTH_PCT
        width_note = "wide_band_max_80"
        skew = 0.0
    elif sid == STRATEGY_BRAINIAC_CURSOR_SUCCESS:
        from raydium_lp1.lp_brainiac_cursor_success import build_brainiac_cursor_open_plan

        plan_bc = build_brainiac_cursor_open_plan(
            pool,
            momentum,
            default_width_pct=default_width_pct,
            skew_use_momentum=skew_use_momentum,
        )
        return plan_bc
    else:
        width_pct = default_width_pct
        width_note = f"default:{width_pct}"

    band: dict[str, Any]
    if sid == STRATEGY_ASYMMETRIC:
        bias = "bullish" if skew >= 0 else "bearish"
        if spot is None:
            band = {"synthetic": True, "order_type": bias, "width_pct": width_pct}
        else:
            b = execute_asymmetric_order(spot, order_type=bias, width_pct=width_pct)
            band = {
                "order_type": bias,
                "lower_quote_per_base": round(b["lower"], 8),
                "upper_quote_per_base": round(b["upper"], 8),
                "spot_quote_per_base": spot,
            }
    elif spot is None:
        lo, hi = lp_range_planner.asymmetric_quote_band(1.0, width_pct, skew)
        band = {
            "lower_quote_per_base": round(lo, 8),
            "upper_quote_per_base": round(hi, 8),
            "synthetic": True,
        }
    else:
        if sid == STRATEGY_TRAILING_SKEW:
            skew = lp_range_planner._clamp(skew * 1.25, -1.0, 1.0)
        lo, hi = lp_range_planner.asymmetric_quote_band(spot, width_pct, skew)
        band = {
            "lower_quote_per_base": round(lo, 8),
            "upper_quote_per_base": round(hi, 8),
            "spot_quote_per_base": spot,
            "spot_source": spot_src,
        }

    return {
        "strategy_id": spec.id,
        "strategy_name": spec.official_name,
        "strategy_description": spec.description,
        "width_pct": round(width_pct, 2),
        "width_note": width_note,
        "skew": round(skew, 3),
        "skew_notes": skew_notes,
        "band": band,
        "execution": "paper_ready",
        "live_hook": "raydium_clmm.open_position",
    }
