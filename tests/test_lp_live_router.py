"""Tests for lp_live_router strategy dispatch."""

from __future__ import annotations

from raydium_lp1.lp_live_router import (
    is_brainiac_strategy,
    live_hook_for_strategy,
    resolve_strategy_id,
)
from raydium_lp1.lp_order_strategies import (
    STRATEGY_ASYMMETRIC,
    STRATEGY_BRAINIAC_CURSOR_SUCCESS,
    STRATEGY_FULL_RANGE,
)
from raydium_lp1.strategy_registry import resolve_lp_order_strategy_id


def test_is_brainiac_strategy():
    assert is_brainiac_strategy(STRATEGY_BRAINIAC_CURSOR_SUCCESS)
    assert not is_brainiac_strategy(STRATEGY_FULL_RANGE)


def test_resolve_strategy_id_from_settings():
    sid = resolve_strategy_id(None, settings={"lp_active_strategy": STRATEGY_ASYMMETRIC})
    assert sid == STRATEGY_ASYMMETRIC


def test_live_hook_brainiac_vs_generic():
    assert "brainiac_cursor_success" in live_hook_for_strategy(STRATEGY_BRAINIAC_CURSOR_SUCCESS)
    assert live_hook_for_strategy(STRATEGY_FULL_RANGE) == "raydium_lp1.live_executor.open_clmm_candidate"


def test_legacy_registry_maps_to_lp_order():
    assert resolve_lp_order_strategy_id("range_order") == STRATEGY_ASYMMETRIC
    assert resolve_lp_order_strategy_id(STRATEGY_FULL_RANGE) == STRATEGY_FULL_RANGE
