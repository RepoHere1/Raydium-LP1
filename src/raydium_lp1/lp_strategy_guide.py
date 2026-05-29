"""LP strategy cards + experiment loop copy for the dashboard settings UI."""

from __future__ import annotations

from typing import Any

from raydium_lp1.lp_order_strategies import STRATEGY_CATALOG


def strategy_cards_for_ui() -> list[dict[str, Any]]:
    """Rich strategy picker content (maps 1:1 to ``lp_active_strategy``)."""

    extra: dict[str, dict[str, str]] = {
        "auto_volatility_pick": {
            "band_hint": "Auto ±12–50%",
            "summary": (
                "Picks centered tight vs ATR width from pool churn and day-range swing. "
                "Good default until you specialize per pair."
            ),
            "when_to_use": "Start here; switch to a fixed style once you know the pair.",
        },
        "centered_tight_range": {
            "band_hint": "±5–15%",
            "summary": (
                "Narrow band symmetric around spot. Best fee density while price chops inside "
                "the band; needs frequent re-centering on volatile SOL/memecoin pairs."
            ),
            "when_to_use": "Quiet pairs or when you can rebalance often.",
        },
        "volatility_atr_width": {
            "band_hint": "ATR-scaled (often ±15–55%)",
            "summary": (
                "Widens the band when day min/max swing or churn is high; fewer out-of-range "
                "(OOR) events, lower fee per dollar than a tight band."
            ),
            "when_to_use": "Degen/meme scanning — solid default after auto.",
        },
        "asymmetric_single_asset": {
            "band_hint": "Single-sided above/below",
            "summary": (
                "Band entirely above spot (bullish / limit-sell style, mostly SOL until price "
                "rises) or below spot (buy-the-dip). High OOR risk if direction is wrong."
            ),
            "when_to_use": "Directional bets (e.g. SOL/DEGEN); pair with momentum skew.",
        },
        "trailing_dynamic_skew": {
            "band_hint": "Skewed band",
            "summary": (
                "Shifts the whole band toward momentum inflow so liquidity sits near where "
                "flow is moving — grid / MM skew."
            ),
            "when_to_use": "Enable lp_skew_use_momentum; hot-tier pools.",
        },
        "standard_full_range": {
            "band_hint": "Wide / passive",
            "summary": (
                "CPMM-like wide CLMM span. Lower fee intensity per dollar but simpler and "
                "almost always in range."
            ),
            "when_to_use": "When you cannot monitor; not for max APR hunting.",
        },
    }

    cards: list[dict[str, Any]] = []
    for spec in STRATEGY_CATALOG:
        x = extra.get(spec.id, {})
        cards.append(
            {
                "id": spec.id,
                "title": spec.official_name,
                "short_label": spec.short_label,
                "band_hint": x.get("band_hint", ""),
                "summary": x.get("summary", spec.description),
                "when_to_use": x.get("when_to_use", ""),
                "raydium_notes": spec.raydium_notes,
            }
        )
    return cards


def experiment_loop_steps() -> dict[str, Any]:
    """Practical A/B loop shown above the strategy picker."""

    return {
        "title": "Practical experiment loop (remember this)",
        "subtitle": (
            "CLMM is not set-and-forget: out-of-range = zero fees and 100% one token until "
            "price returns or you rebalance. On ~0.005 SOL opens, rent + gas matter as much as APR."
        ),
        "steps": [
            {
                "n": 1,
                "title": "Pick LP order style below",
                "body": "Click a strategy card, then Save settings. Next LIVE open uses that style.",
            },
            {
                "n": 2,
                "title": "DRY_RUN first (optional)",
                "body": "Stay on DRY_RUN, run scan, copy pool ids from candidates, sanity-check the pair.",
            },
            {
                "n": 3,
                "title": "Small LIVE open",
                "body": "Arm LIVE, use position_size_sol (e.g. 0.005), open row #1 or pick a pool id.",
            },
            {
                "n": 4,
                "title": "Read LP style stats",
                "body": (
                    "Positions tab → LIVE trades (LP style column) + LP style experiment table: "
                    "in-range@open, OOR@open, fees USD."
                ),
            },
            {
                "n": 5,
                "title": "Change strategy & repeat",
                "body": "Switch lp_active_strategy, save, open another small position — compare groups.",
            },
            {
                "n": 6,
                "title": "Keep the winner",
                "body": (
                    "After 3+ opens per style, favor the style with fees + in-range@open, not just "
                    "headline APR at entry."
                ),
            },
        ],
        "active_management": (
            "Raydium CLMM: tighter range = more fees in-range, more OOR events if you do not "
            "rebalance. Track results in live_lp_style_report on the dashboard."
        ),
    }
