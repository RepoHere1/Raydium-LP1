import unittest

from raydium_lp1.price_impact_guard import (
    PriceImpactGuardConfig,
    estimate_price_impact_pct,
    evaluate_price_impact_guard,
)


class PriceImpactGuardTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        ok, _ = evaluate_price_impact_guard(
            {"liquidity_usd": 100.0},
            PriceImpactGuardConfig(enabled=False),
            max_position_usd=25.0,
        )
        self.assertTrue(ok)

    def test_zero_tvl_returns_100_pct_impact(self):
        impact = estimate_price_impact_pct({"liquidity_usd": 0}, max_position_usd=25.0)
        self.assertEqual(impact, 100.0)

    def test_large_pool_low_impact(self):
        impact = estimate_price_impact_pct(
            {"liquidity_usd": 5_000_000}, max_position_usd=25.0
        )
        self.assertLess(impact, 0.01)

    def test_small_pool_high_impact_rejected(self):
        ok, reason = evaluate_price_impact_guard(
            {"liquidity_usd": 50.0},
            PriceImpactGuardConfig(enabled=True, max_impact_percent=1.0),
            max_position_usd=25.0,
        )
        self.assertFalse(ok)
        self.assertIn("price impact", reason)

    def test_borderline_pool_under_threshold(self):
        ok, _ = evaluate_price_impact_guard(
            {"liquidity_usd": 100_000.0},
            PriceImpactGuardConfig(enabled=True, max_impact_percent=1.0),
            max_position_usd=25.0,
        )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
