"""Tests for shadow PnL / exit modeling."""

from __future__ import annotations

import unittest

from raydium_lp1 import pnl_estimate


class PnlEstimateTests(unittest.TestCase):
    def test_net_model_subtracts_entry_and_priority(self):
        pool = {
            "id": "p1",
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "MEME",
            "sellability": {
                "ok": True,
                "token_a": {
                    "ok": True,
                    "target_symbol": "SOL",
                    "best_price": 50_000_000.0,
                },
                "token_b": {
                    "ok": True,
                    "target_symbol": "SOL",
                    "best_price": 40_000_000.0,
                },
            },
        }
        out = pnl_estimate.build_shadow_activity_for_pool(
            pool,
            entry_assumption_sol=0.1,
            priority_fee_reserve_sol=0.00002,
        )
        self.assertEqual(out["status"], "modeled")
        self.assertAlmostEqual(out["exit_modeled_gross_sol_floor"], 0.04)
        self.assertAlmostEqual(out["pnl_sol_net_model"], 0.04 - 0.1 - 0.00002)

    def test_missing_sellability(self):
        out = pnl_estimate.build_shadow_activity_for_pool({}, entry_assumption_sol=1.0, priority_fee_reserve_sol=0.0)
        self.assertEqual(out["status"], "no_sellability_or_not_ok")


if __name__ == "__main__":
    unittest.main()
