import time
import unittest
from unittest.mock import patch

from raydium_lp1 import momentum_detective


class DetectiveTests(unittest.TestCase):
    def test_volume_surge_detected(self):
        pool = {
            "id": "p1",
            "liquidity_usd": 10_000,
            "volume_24h_usd": 30_000,
            "fee_24h_usd": 50,
            "apr": 800,
            "open_time": int(time.time()) - 24 * 3600,
            "raw": {
                "day": {"volume": 30000, "volumeFee": 50, "apr": 800, "volumeQuote": 1e6},
                "week": {"volume": 70_000, "volumeQuote": 2e6, "volumeFee": 80},
            },
        }
        det = momentum_detective.run_detective(pool)
        self.assertGreater(det.detective_score, 40)
        self.assertTrue(
            any(t in det.sniff_tags for t in ("volume_accelerating", "volume_surging_vs_7d")),
            det.sniff_tags,
        )

    def test_market_leaderboard_flag(self):
        pool = {"id": "leader-1", "liquidity_usd": 5000, "volume_24h_usd": 2000, "raw": {"day": {}}}
        pulse = {"volume24h_leader": {"leader-1", "other"}}
        det = momentum_detective.run_detective(pool, market_pulse=pulse)
        self.assertIn("on_volume_leaderboard", det.sniff_tags)

    def test_build_hot_top25(self):
        candidates = []
        for i in range(30):
            candidates.append(
                {
                    "id": f"p{i}",
                    "mint_a_symbol": "S",
                    "mint_b_symbol": f"T{i}",
                    "liquidity_usd": 5000 + i,
                    "volume_24h_usd": 1000,
                    "apr": 500,
                    "momentum": {
                        "combined_score": 80 - i,
                        "score": 70 - i,
                        "tier": "hot" if i < 5 else "enter_bias",
                        "detective": {"sniff_tags": ["buyer_flow_ok"]},
                    },
                }
            )
        hot = momentum_detective.build_hot_leaderboard(candidates, top_n=25)
        self.assertEqual(len(hot), 25)
        self.assertEqual(hot[0]["combined_score"], 80)


if __name__ == "__main__":
    unittest.main()
