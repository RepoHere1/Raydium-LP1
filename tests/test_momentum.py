import time
import unittest

from raydium_lp1 import momentum
from raydium_lp1.momentum import MomentumConfig, TIER_EXIT, TIER_HOT


class MomentumScoreTests(unittest.TestCase):
    def _hot_pool(self) -> dict:
        return {
            "id": "pool-hot",
            "liquidity_usd": 15_000.0,
            "volume_24h_usd": 45_000.0,
            "volume_7d_usd": 90_000.0,
            "apr": 1200.0,
            "fee_24h_usd": 80.0,
            "open_time": int(time.time()) - 36 * 3600,
            "raw": {"week": {"volume": 90_000.0}},
        }

    def test_high_velocity_scores_hot(self):
        cfg = MomentumConfig(enabled=True, min_volume_tvl_ratio=0.5, hold_hours=24)
        m = momentum.assess_momentum(self._hot_pool(), cfg)
        self.assertGreaterEqual(m.score, 55)
        self.assertIn(m.tier, (TIER_HOT, "enter_bias"))
        self.assertGreater(m.volume_tvl_ratio, 2.0)

    def test_dust_pool_exit_tier(self):
        cfg = MomentumConfig(enabled=True, min_tvl_usd=500.0)
        pool = {
            "liquidity_usd": 0.01,
            "volume_24h_usd": 100.0,
            "apr": 90_000.0,
            "fee_24h_usd": 0.0,
            "open_time": 0,
        }
        m = momentum.assess_momentum(pool, cfg)
        self.assertEqual(m.tier, TIER_EXIT)
        self.assertTrue(m.exit_watch)

    def test_volume_accel_detects_surge(self):
        pool = {
            "liquidity_usd": 5000,
            "volume_24h_usd": 20_000,
            "apr": 800,
            "fee_24h_usd": 20,
            "raw": {"week": {"volume": 35_000}},
        }
        self.assertGreater(momentum.volume_accel_ratio(pool), 2.0)

    def test_gate_rejects_low_score_when_required(self):
        cfg = MomentumConfig(enabled=True, min_score=80, require_min_score=True)
        pool = {
            "liquidity_usd": 300,
            "volume_24h_usd": 50,
            "apr": 100,
            "fee_24h_usd": 1,
        }
        m = momentum.assess_momentum(pool, cfg)
        ok, reasons = momentum.gate_candidate(pool, m, cfg)
        self.assertFalse(ok)
        self.assertTrue(reasons)

    def test_health_critical_forces_exit(self):
        cfg = MomentumConfig(enabled=True)
        pool = self._hot_pool()
        health = {"score": "critical", "reasons": ["TVL collapsed"]}
        m = momentum.assess_momentum(pool, cfg, health=health)
        self.assertEqual(m.tier, TIER_EXIT)


class StrategyMomentumTests(unittest.TestCase):
    def test_momentum_preset_merges_extras(self):
        from raydium_lp1 import strategies

        merged = strategies.apply_strategy({"dry_run": True}, "momentum")
        self.assertEqual(merged["strategy"], "momentum")
        self.assertTrue(merged.get("momentum_enabled"))
        self.assertEqual(merged["min_liquidity_usd"], 5000)


if __name__ == "__main__":
    unittest.main()
