"""Tests for BRAINIAC-CURSOR-SUCCESS order type."""

from __future__ import annotations

from raydium_lp1.lp_brainiac_cursor_success import (
    MICRO_DEPOSIT_PAY_ONLY_USD,
    PLACEMENT_REASONING,
    SETTLEMENT_REASONING,
    STRATEGY_BRAINIAC_CURSOR_SUCCESS,
    SYNOPSIS,
    WIDE_WIDTH_PCT,
    brainiac_micro_pay_only_kwargs,
    build_brainiac_cursor_open_plan,
    open_kwargs_from_plan,
    resolve_brainiac_live_auto_policy,
    ticks_from_skew,
)
from raydium_lp1.lp_pay_mint import PayMintResolution
from raydium_lp1.lp_order_strategies import (
    ALL_STRATEGY_IDS,
    STRATEGY_BRAINIAC_CURSOR_SUCCESS as SID_OS,
    catalog_dict,
    get_strategy,
)


def test_strategy_registered_in_catalog():
    assert STRATEGY_BRAINIAC_CURSOR_SUCCESS in ALL_STRATEGY_IDS
    assert SID_OS == STRATEGY_BRAINIAC_CURSOR_SUCCESS
    spec = get_strategy(STRATEGY_BRAINIAC_CURSOR_SUCCESS)
    assert spec is not None
    assert "BRAINIAC-CURSOR-SUCCESS" in spec.official_name
    assert "80%" in spec.official_name
    assert "escrow" in spec.description.lower() or "rent" in spec.description.lower()
    ids = {c["id"] for c in catalog_dict()}
    assert STRATEGY_BRAINIAC_CURSOR_SUCCESS in ids


def test_ticks_from_skew_total_width_80():
    lo, hi = ticks_from_skew(80.0, 0.0)
    assert abs(lo - 40.0) < 0.01
    assert abs(hi - 40.0) < 0.01
    lo2, hi2 = ticks_from_skew(80.0, -0.4)
    assert lo2 > hi2
    assert abs(lo2 + hi2 - 80.0) < 0.01


def test_open_plan_and_kwargs_no_pay_only():
    pool = {
        "id": "CXuK5H4TZgb28vuucNoJh8LXRmR4VjdEuL6pXmMenSod",
        "price": 75000.0,
        "liquidity_usd": 50000.0,
        "fee_24h_usd": 100.0,
        "volume_24h_usd": 200000.0,
        "raw": {"day": {"priceMin": 60000.0, "priceMax": 90000.0}},
    }
    plan = build_brainiac_cursor_open_plan(pool, None)
    assert plan["strategy_id"] == STRATEGY_BRAINIAC_CURSOR_SUCCESS
    assert plan["width_pct"] == WIDE_WIDTH_PCT
    assert "brainiac_placement" in plan
    assert plan["open_requirements"]["force_pay_token_only"] is False
    assert plan["open_requirements"]["fund_non_pay_from_pay_mint_only"] is True
    assert plan["reasoning"]["placement"] == list(PLACEMENT_REASONING)
    assert plan["reasoning"]["settlement"] == list(SETTLEMENT_REASONING)
    assert "settlement_policy" in plan
    kw = open_kwargs_from_plan(plan)
    assert kw["pay_mint_only"] is False
    assert kw["wide_range"] is False
    assert kw["wallet_inventory_full_range"] is True
    assert kw["tick_lower_pct_below"] > 0
    assert kw["tick_upper_pct_above"] > 0


def test_synopsis_nonempty():
    assert len(SYNOPSIS) > 40


def test_auto_policy_funds_when_wallet_short():
    auto = resolve_brainiac_live_auto_policy(1.0)
    assert auto.skip_fund_swap is False
    assert auto.fund_non_pay_fraction <= 0.35
    assert auto.wide_width_pct == WIDE_WIDTH_PCT
    assert any("will fund" in n.lower() for n in auto.notes)


def test_auto_policy_prefers_pay_only_under_two_dollars():
    auto = resolve_brainiac_live_auto_policy(0.25)
    assert auto.prefer_pay_only_open is True
    assert auto.band_tick_steps_cap <= 14
    assert any("pay-only" in n.lower() for n in auto.notes)

    auto2 = resolve_brainiac_live_auto_policy(3.0)
    assert auto2.prefer_pay_only_open is False


def test_micro_pay_only_kwargs_single_sided_usdc():
    pay = PayMintResolution(
        pay_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        pay_symbol="USDC",
        alt_mint="FRE3HQDTWuhLAvWKapwLMzbw3ZSMdh76CXQqBw2bEJeV",
        alt_symbol="GDER",
        pay_is_mint_a=False,
    )
    kw = brainiac_micro_pay_only_kwargs(pay, deposit_usd=0.25, band_tick_steps_cap=14)
    assert kw["pay_mint_only"] is True
    assert kw["wallet_inventory_full_range"] is False
    assert kw["single_side"] == "below"
    assert kw["band_tick_steps"] <= 14
    assert kw["input_mint"] == pay.pay_mint


def test_open_kwargs_cap_steps_for_one_dollar():
    pool = {
        "id": "CXuK5H4TZgb28vuucNoJh8LXRmR4VjdEuL6pXmMenSod",
        "price": 75000.0,
        "liquidity_usd": 50000.0,
        "fee_24h_usd": 100.0,
        "volume_24h_usd": 200000.0,
        "raw": {"day": {"priceMin": 60000.0, "priceMax": 90000.0}},
    }
    plan = build_brainiac_cursor_open_plan(pool, None)
    kw = open_kwargs_from_plan(plan, deposit_usd=1.0, band_tick_steps_cap=24)
    assert kw["band_tick_steps"] <= 24
