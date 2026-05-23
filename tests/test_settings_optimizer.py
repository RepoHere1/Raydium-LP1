import json
import tempfile
import unittest
from pathlib import Path

from raydium_lp1.settings_optimizer import (
    analyze,
    apply_recommendations,
    budget_usd_breakdown,
    run_cycle,
)


class SettingsOptimizerTests(unittest.TestCase):
    def test_budget_usd_full_range_fraction(self):
        b = budget_usd_breakdown(
            {
                "position_size_sol": 0.1,
                "lp_main_budget_fraction": 0.75,
                "lp_full_range_budget_fraction": 0.25,
                "lp_full_range_parallel": True,
            },
            sol_usd=200.0,
        )
        self.assertEqual(b["position_notional_usd"], 20.0)
        self.assertEqual(b["lp_main_budget_usd"], 15.0)
        self.assertEqual(b["lp_full_range_budget_usd"], 5.0)

    def test_analyze_produces_five_pulse_lines(self):
        dash = {
            "last_scan": {
                "scanned_count": 1000,
                "candidate_count": 10,
                "rejected_count": 990,
                "health_summary": {"healthy": 8, "warning": 2, "critical": 0},
            },
            "open_positions": [
                {
                    "pair": "A/SOL",
                    "apr": 120,
                    "liquidity_usd": 500_000,
                    "volume_24h_usd": 200_000,
                    "health": "healthy",
                }
            ],
            "recent_alerts": [],
            "wallet_capacity": {"capacity": {"max_positions": 0}},
        }
        snap = analyze(dashboard=dash, settings={"settings_optimizer_auto_apply": False})
        self.assertEqual(len(snap.market_pulse), 5)
        self.assertIn("min_apr", snap.recommended_patch)

    def test_auto_apply_writes_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            dash = Path(tmp) / "dashboard.json"
            settings.write_text(
                json.dumps({"min_apr": 999, "settings_optimizer_auto_apply": True}) + "\n",
                encoding="utf-8",
            )
            dash.write_text(
                json.dumps(
                    {
                        "open_positions": [{"apr": 80, "liquidity_usd": 300_000, "volume_24h_usd": 50_000}],
                        "last_scan": {
                            "scanned_count": 100,
                            "candidate_count": 1,
                            "rejected_count": 99,
                            "health_summary": {},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            snap = run_cycle(settings_path=settings, dashboard_path=dash)
            raw = json.loads(settings.read_text())
            self.assertLess(raw["min_apr"], 999)


if __name__ == "__main__":
    unittest.main()
