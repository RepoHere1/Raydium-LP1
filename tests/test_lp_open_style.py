"""LP open style resolution from settings."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from raydium_lp1.lp_open_style import annotate_position_style, resolve_live_open_style
from raydium_lp1.lp_order_strategies import STRATEGY_ASYMMETRIC, STRATEGY_CENTERED_TIGHT
from raydium_lp1.lp_style_performance import build_live_style_report


class LpOpenStyleTests(unittest.TestCase):
    def _pool(self) -> dict:
        return {
            "id": "pool1",
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "DEGEN",
            "liquidity_usd": 50_000,
            "volume_24h_usd": 10_000,
            "raw": {"day": {"priceMin": 70_000, "priceMax": 90_000}},
            "momentum": {"tier": "hot", "score": 80, "detective": {"inflow_bias": 20}},
        }

    def test_asymmetric_strategy_uses_single_side(self) -> None:
        cfg = SimpleNamespace(
            lp_active_strategy=STRATEGY_ASYMMETRIC,
            lp_default_range_width_pct=15.0,
            lp_skew_use_momentum=True,
            lp_open_pay_token_only=False,
        )
        style = resolve_live_open_style(cfg, self._pool())
        self.assertIn(style.placement, ("single_above", "single_below"))
        self.assertIn(style.open_kwargs.get("single_side"), ("above", "below"))
        self.assertIn("CLMM", style.lp_style_label)

    def test_centered_strategy_no_single_side_when_pay_only_off(self) -> None:
        cfg = SimpleNamespace(
            lp_active_strategy=STRATEGY_CENTERED_TIGHT,
            lp_default_range_width_pct=12.0,
            lp_skew_use_momentum=False,
            lp_open_pay_token_only=False,
        )
        style = resolve_live_open_style(cfg, self._pool())
        self.assertEqual(style.placement, "centered")
        self.assertIsNone(style.open_kwargs.get("single_side"))

    def test_backfill_from_clmm_result(self) -> None:
        row = annotate_position_style(
            {
                "pair": "SOL/DEGEN",
                "clmm_result": {
                    "single_side_mode": "above",
                    "band_tick_steps": 10,
                    "tick_lower": 1,
                    "tick_upper": 10,
                    "tick_current": 0,
                },
            }
        )
        self.assertIn("CLMM", row["lp_style_label"])
        self.assertEqual(row["lp_placement"], "single_above")

    def test_style_report_groups(self) -> None:
        report = build_live_style_report(
            [
                {
                    "lp_style_key": "a|single_above|w15",
                    "lp_style_label": "CLMM · single above · 15%",
                    "apr": 100,
                    "fees_collected_usd": 0.01,
                    "clmm_result": {"tick_lower": 1, "tick_upper": 10, "tick_current": 5},
                }
            ]
        )
        self.assertEqual(report["open_count"], 1)
        self.assertEqual(len(report["style_groups"]), 1)


if __name__ == "__main__":
    unittest.main()
