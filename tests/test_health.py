import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1 import health
from raydium_lp1.scanner import ScannerConfig, scan


class HealthAssessmentTests(unittest.TestCase):
    def _pool(self, pool_id="pool-1", tvl=1000.0, volume=2000.0, apr=1000.0):
        return {
            "id": pool_id,
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "TEST",
            "liquidity_usd": tvl,
            "volume_24h_usd": volume,
            "apr": apr,
        }

    def test_first_sighting_is_healthy_baseline(self):
        history: dict = {}
        health.record_snapshot(history, self._pool(tvl=1000, volume=2000))
        assessment = health.assess_health(history, self._pool(tvl=1000, volume=2000))
        self.assertEqual(assessment.score, "healthy")
        self.assertEqual(assessment.tvl_entry, 1000)

    def test_critical_when_tvl_drops_30_percent(self):
        history: dict = {}
        health.record_snapshot(history, self._pool(tvl=1000, volume=2000))
        # Same pool, fresh scan but TVL is now 600 (40% drop).
        health.record_snapshot(history, self._pool(tvl=600, volume=2000))
        assessment = health.assess_health(history, self._pool(tvl=600, volume=2000))
        self.assertEqual(assessment.score, "critical")
        self.assertGreaterEqual(assessment.tvl_drop_pct, 0.30)

    def test_warning_when_tvl_drops_between_15_and_30_percent(self):
        history: dict = {}
        health.record_snapshot(history, self._pool(tvl=1000, volume=2000))
        health.record_snapshot(history, self._pool(tvl=800, volume=2000))
        assessment = health.assess_health(history, self._pool(tvl=800, volume=2000))
        self.assertEqual(assessment.score, "warning")

    def test_volume_near_zero_marks_critical(self):
        history: dict = {}
        health.record_snapshot(history, self._pool(tvl=1000, volume=5000))
        health.record_snapshot(history, self._pool(tvl=1000, volume=5))
        assessment = health.assess_health(history, self._pool(tvl=1000, volume=5))
        self.assertEqual(assessment.score, "critical")
        self.assertTrue(any("volume" in r.lower() for r in assessment.reasons))

    def test_volume_collapse_marks_warning(self):
        history: dict = {}
        health.record_snapshot(history, self._pool(tvl=1000, volume=10_000))
        health.record_snapshot(history, self._pool(tvl=1000, volume=400))
        assessment = health.assess_health(history, self._pool(tvl=1000, volume=400))
        self.assertEqual(assessment.score, "warning")

    def test_history_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            history = {}
            health.record_snapshot(history, self._pool(tvl=1000, volume=2000))
            health.save_history(history, path)
            reloaded = health.load_history(path)
            self.assertIn("pool-1", reloaded)
            self.assertEqual(reloaded["pool-1"]["entry"]["tvl"], 1000)

    def test_max_snapshots_caps_growth(self):
        history: dict = {}
        for i in range(10):
            health.record_snapshot(
                history, self._pool(tvl=1000, volume=2000), max_snapshots=3
            )
        self.assertEqual(len(history["pool-1"]["snapshots"]), 3)


class ScannerHealthIntegrationTests(unittest.TestCase):
    def test_health_attached_to_candidates(self):
        config = ScannerConfig(
            min_apr=100,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            require_sell_route=False,
            track_liquidity_health=True,
        )
        api_response = {
            "data": {
                "data": [
                    {
                        "id": "pool-x",
                        "apr24h": 1500,
                        "tvl": 5000,
                        "volume24h": 1000,
                        "mintA": {"symbol": "SOL", "address": "sol"},
                        "mintB": {"symbol": "TEST", "address": "test"},
                    }
                ]
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.json"
            config = ScannerConfig(
                min_apr=100,
                min_liquidity_usd=10,
                min_volume_24h_usd=10,
                require_sell_route=False,
                track_liquidity_health=True,
                liquidity_history_path=str(history_path),
            )
            with patch("raydium_lp1.scanner.fetch_json", return_value=api_response):
                report = scan(config)
            self.assertEqual(report["candidate_count"], 1)
            candidate = report["candidates"][0]
            self.assertIn("health", candidate)
            self.assertIn(candidate["health"]["score"], ("healthy", "warning", "critical"))
            self.assertIn("health_summary", report)
            self.assertTrue(history_path.exists())


if __name__ == "__main__":
    unittest.main()
