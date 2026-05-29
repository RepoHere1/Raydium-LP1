"""Pay-token funding planner (no network)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from raydium_lp1.pay_token_funding import (
    compute_pay_shortfall,
    estimate_sol_for_stable_shortfall,
    plan_pay_token_funding,
)


class PayTokenFundingTests(unittest.TestCase):
    def test_shortfall_when_usdc_low(self) -> None:
        s = compute_pay_shortfall(0.25, 0.05, buffer_pct=0.03, dust_human=0.02)
        self.assertGreater(s["shortfall_human"], 0.15)
        self.assertAlmostEqual(s["required_human"], 0.2575, places=4)

    def test_no_shortfall_when_balance_ok(self) -> None:
        s = compute_pay_shortfall(0.15, 0.20, buffer_pct=0.03, dust_human=0.02)
        self.assertEqual(s["shortfall_human"], 0.0)

    def test_plan_skips_sol_pay(self) -> None:
        plan = plan_pay_token_funding(
            "SOL",
            "So11111111111111111111111111111111111111112",
            0.1,
            {"sol_balance": 1.0, "usdc_balance": 0},
        )
        self.assertFalse(plan["needed"])

    def test_plan_needs_swap_for_usdc(self) -> None:
        plan = plan_pay_token_funding(
            "USDC",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            0.25,
            {"sol_balance": 0.5, "usdc_balance": 0.02},
            config=SimpleNamespace(lp_pay_funding_buffer_pct=0.03),
            sol_price_usd=200.0,
        )
        self.assertTrue(plan["needed"])
        self.assertGreater(plan["amount_lamports"], 0)

    def test_estimate_sol_for_shortfall(self) -> None:
        sol = estimate_sol_for_stable_shortfall(0.20, sol_price_usd=200.0, swap_buffer=1.1)
        self.assertAlmostEqual(sol, 0.0011, places=4)


if __name__ == "__main__":
    unittest.main()
