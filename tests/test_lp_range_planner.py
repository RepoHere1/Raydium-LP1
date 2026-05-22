import unittest

from raydium_lp1 import lp_range_planner


class LPRangePlannerTests(unittest.TestCase):
    def test_asymmetric_band_bullish_skew(self):
        lo, hi = lp_range_planner.asymmetric_quote_band(1.0, 20.0, 1.0)
        self.assertLess(lo, 1.0)
        self.assertGreater(hi, 1.0)
        self.assertGreater((hi - 1.0), (1.0 - lo))

    def test_pick_width_widens_on_high_swing(self):
        pool = {
            "id": "p1",
            "liquidity_usd": 10_000,
            "volume_24h_usd": 50_000,
            "raw": {"day": {"volume": 50_000, "priceMin": 1.0, "priceMax": 1.6}},
        }
        w, note = lp_range_planner.pick_width_pct(
            pool,
            None,
            candidates=(12.0, 20.0, 30.0, 50.0),
            default_pct=20.0,
            mode="auto",
            risk_profile="balanced",
        )
        self.assertGreaterEqual(w, 20.0, note)

    def test_expand_band_edge_buffer(self) -> None:
        lo, hi = lp_range_planner.expand_band_edge_buffer(0.9, 1.1, 1.0, 3.0)
        self.assertLess(lo, 0.9)
        self.assertGreater(hi, 1.1)

    def test_clmm_dynamic_sweet_spot_snaps_to_candidate(self) -> None:
        pool = {
            "id": "p1",
            "liquidity_usd": 10_000,
            "volume_24h_usd": 50_000,
            "raw": {"day": {"volume": 50_000, "priceMin": 1.0, "priceMax": 1.6}},
        }
        w, note = lp_range_planner.pick_width_pct(
            pool,
            None,
            candidates=(12.0, 20.0, 30.0, 50.0),
            default_pct=20.0,
            mode="clmm_dynamic_sweet_spot",
            risk_profile="balanced",
            sweet_width_candidates=(8.0, 20.0, 40.0),
        )
        self.assertIn(w, (8.0, 20.0, 40.0))
        self.assertIn("clmm_dynamic_sweet_spot", note)

    def test_plan_includes_parallel_full_range(self) -> None:
        cfg = lp_range_planner.LPPlannerConfig(
            enabled=True,
            full_range_parallel=True,
            full_range_budget_fraction=0.25,
            main_budget_fraction=0.75,
        )
        pool = {
            "id": "x",
            "mint_a_symbol": "A",
            "mint_b_symbol": "B",
            "liquidity_usd": 1000,
            "volume_24h_usd": 5000,
            "type": "Concentrated",
            "subtypes": ["Clmm"],
            "raw": {"day": {"volume": 5000, "priceMin": 0.99, "priceMax": 1.01}},
        }
        plan = lp_range_planner.plan_for_pool(pool, None, cfg)
        self.assertTrue(plan["parallel_full_range"]["enabled"])
        self.assertIn("lower_quote_per_base", plan["concentrated"])
        self.assertIn("raydium_clmm_terms", plan)

    def test_momentum_skew_exit_tier_without_detective_dict(self) -> None:
        """Regression: tier exit_now used `sk` before assignment when detective was missing."""

        sk, notes = lp_range_planner.momentum_skew({"tier": "exit_now"}, use_momentum=True)
        self.assertLess(sk, 0.0)
        self.assertTrue(any("exit" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
