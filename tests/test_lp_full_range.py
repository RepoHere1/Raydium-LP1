"""CLMM wide-band (max 80%) — not literal pool min/max ticks."""

from __future__ import annotations

import unittest

from raydium_lp1.lp_full_range import (
    DEFAULT_WIDE_BAND_WIDTH_PCT,
    clmm_position_in_range,
    open_kwargs_for_wide_band,
    position_spans_full_ticks,
    tick_bounds_for_spacing,
)
from raydium_lp1.lp_open_style import resolve_live_open_style
from raydium_lp1.lp_order_strategies import STRATEGY_FULL_RANGE
from types import SimpleNamespace


class LpWideBandTests(unittest.TestCase):
    def test_tick_bounds_spacing_1(self) -> None:
        lo, hi = tick_bounds_for_spacing(1)
        self.assertEqual(lo, -443636)
        self.assertEqual(hi, 443636)

    def test_literal_ticks_detected(self) -> None:
        lo, hi = tick_bounds_for_spacing(10)
        clmm = {
            "tick_lower": lo,
            "tick_upper": hi,
            "tick_current": 0,
            "tick_spacing": 10,
        }
        self.assertTrue(position_spans_full_ticks(clmm))

    def test_wide_band_not_always_in_range(self) -> None:
        row = {"lp_strategy_id": STRATEGY_FULL_RANGE, "lp_placement": "wide_band"}
        clmm = {
            "wide_range": True,
            "tick_lower": -1000,
            "tick_upper": 1000,
            "tick_current": 5000,
            "tick_spacing": 10,
        }
        self.assertFalse(clmm_position_in_range(row, clmm))

    def test_resolve_open_style_uses_wide_band_not_literal(self) -> None:
        pool = {
            "mint_a": "So11111111111111111111111111111111111111112",
            "mint_b": "Alt",
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "DEGEN",
        }
        cfg = SimpleNamespace(
            lp_active_strategy=STRATEGY_FULL_RANGE,
            lp_default_range_width_pct=40.0,
            lp_skew_use_momentum=False,
            lp_open_pay_token_only=False,
            allowed_quote_symbols={"SOL", "USDC", "USDT"},
        )
        style = resolve_live_open_style(cfg, pool)
        self.assertFalse(style.open_kwargs.get("full_range"))
        self.assertTrue(style.open_kwargs.get("wide_range"))
        self.assertEqual(style.placement, "wide_band")
        self.assertEqual(style.width_pct, DEFAULT_WIDE_BAND_WIDTH_PCT)
        self.assertAlmostEqual(style.open_kwargs["tick_lower_pct_below"], 40.0)
        self.assertAlmostEqual(style.open_kwargs["tick_upper_pct_above"], 40.0)

    def test_open_kwargs_for_wide_band_caps_at_80(self) -> None:
        kw = open_kwargs_for_wide_band(width_pct=100.0)
        self.assertEqual(kw["wide_range_width_pct"], 80.0)
        self.assertEqual(kw["tick_lower_pct_below"], 40.0)


if __name__ == "__main__":
    unittest.main()
