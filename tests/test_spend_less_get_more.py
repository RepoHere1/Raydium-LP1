"""SPEND LESS=GET MORE planner."""

from __future__ import annotations

import unittest

from raydium_lp1.lp_full_range import open_kwargs_for_wide_band
from raydium_lp1.lp_order_strategies import STRATEGY_ASYMMETRIC
from raydium_lp1.spend_less_get_more import TAG, analyze_open_plan


class SpendLessTests(unittest.TestCase):
    def test_wide_three_dollar_blocked(self) -> None:
        plan = analyze_open_plan(
            requested_deposit_usd=3.0,
            open_kwargs=open_kwargs_for_wide_band(),
            pay_symbol="SOL",
            balance_sol=0.18,
            reserve_sol=0.002,
            settings={"max_rent_escrow_pct_of_deposit": 10, "sol_price_usd": 180},
            strategy_id="standard_full_range",
        )
        self.assertEqual(plan.tag, TAG)
        self.assertFalse(plan.ok)
        self.assertGreater(plan.min_deposit_usd_rent_cap, 50)

    def test_sol_single_sided_clamp(self) -> None:
        kw = {
            "single_side": "above",
            "single_side_width_pct": 20.0,
            "wide_range": False,
        }
        plan = analyze_open_plan(
            requested_deposit_usd=20.0,
            open_kwargs=kw,
            pay_symbol="SOL",
            balance_sol=0.18,
            reserve_sol=0.002,
            settings={
                "max_rent_escrow_pct_of_deposit": 10,
                "sol_price_usd": 180,
                "spend_less_auto_clamp_deposit": True,
            },
            strategy_id=STRATEGY_ASYMMETRIC,
        )
        self.assertTrue(plan.clamped or plan.effective_deposit_usd < 20.0)


if __name__ == "__main__":
    unittest.main()
