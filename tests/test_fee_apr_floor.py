import unittest

from raydium_lp1.fee_apr_floor import (
    FeeAprFloorConfig,
    estimate_fee_apr_percent,
    evaluate_fee_apr_floor,
)


class FeeAprFloorTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        ok, _ = evaluate_fee_apr_floor({"liquidity_usd": 0}, FeeAprFloorConfig(enabled=False))
        self.assertTrue(ok)

    def test_zero_tvl_yields_zero_fee_apr(self):
        self.assertEqual(estimate_fee_apr_percent({"liquidity_usd": 0, "fee_24h_usd": 5}), 0.0)

    def test_real_pool_fee_apr(self):
        apr = estimate_fee_apr_percent({"liquidity_usd": 1_000_000, "fee_24h_usd": 1_000})
        self.assertAlmostEqual(apr, 36.5)

    def test_rejects_when_fee_apr_below_floor(self):
        ok, reason = evaluate_fee_apr_floor(
            {"liquidity_usd": 1_000_000, "fee_24h_usd": 10},
            FeeAprFloorConfig(enabled=True, min_fee_apr_percent=30.0),
        )
        self.assertFalse(ok)
        self.assertIn("fee-only APR", reason)

    def test_accepts_when_fee_apr_above_floor(self):
        ok, _ = evaluate_fee_apr_floor(
            {"liquidity_usd": 1_000_000, "fee_24h_usd": 1_500},
            FeeAprFloorConfig(enabled=True, min_fee_apr_percent=30.0),
        )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
