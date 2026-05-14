import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1 import emergency, health
from raydium_lp1.scanner import ScannerConfig, scan


class SwapPlanTests(unittest.TestCase):
    def test_build_swap_plan_uses_slippage_bps(self):
        plan = emergency.build_swap_plan(
            "RUGMINT", "RUG", amount=1_000_000, max_slippage_pct=0.30
        )
        self.assertTrue(plan.dry_run)
        self.assertEqual(plan.slippage_bps, 3000)
        self.assertIn("slippageBps=3000", plan.quote_url)
        self.assertEqual(plan.output_mint, emergency.BASE_TOKENS["SOL"])

    def test_plan_emergency_close_skips_base_token(self):
        pool = {
            "id": "p",
            "mint_a": "solmint",
            "mint_a_symbol": "SOL",
            "mint_b": "rugmint",
            "mint_b_symbol": "RUG",
        }
        plans = emergency.plan_emergency_close(pool)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].input_symbol, "RUG")

    def test_build_alert_captures_reasons_and_plans(self):
        pool = {
            "id": "rug-pool",
            "mint_a": "solmint",
            "mint_a_symbol": "SOL",
            "mint_b": "rugmint",
            "mint_b_symbol": "RUG",
        }
        assessment = health.HealthAssessment(
            pool_id="rug-pool",
            score="critical",
            reasons=["TVL down 50% from entry"],
            tvl_now=500,
            tvl_entry=1000,
            tvl_drop_pct=0.5,
            volume_now=10,
            volume_entry=2000,
            snapshot_count=3,
        )
        alert = emergency.build_alert(pool, assessment)
        self.assertEqual(alert.severity, "critical")
        self.assertTrue(alert.dry_run)
        self.assertEqual(alert.pair, "SOL/RUG")
        self.assertEqual(len(alert.swap_plans), 1)
        self.assertEqual(alert.swap_plans[0]["output_symbol"], "SOL")

    def test_run_emergency_pass_only_triggers_on_critical(self):
        ok_pool = {"id": "ok", "mint_a_symbol": "SOL", "mint_b_symbol": "T", "mint_a": "a", "mint_b": "b"}
        bad_pool = {"id": "bad", "mint_a_symbol": "SOL", "mint_b_symbol": "R", "mint_a": "a", "mint_b": "r"}
        ok_assessment = health.HealthAssessment(
            pool_id="ok", score="healthy", reasons=[], tvl_now=100, tvl_entry=100,
            tvl_drop_pct=0, volume_now=1000, volume_entry=1000, snapshot_count=1,
        )
        bad_assessment = health.HealthAssessment(
            pool_id="bad", score="critical", reasons=["nuked"], tvl_now=10, tvl_entry=100,
            tvl_drop_pct=0.9, volume_now=1, volume_entry=1000, snapshot_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.json"
            printed: list[str] = []
            alerts = emergency.run_emergency_pass(
                [(ok_pool, ok_assessment), (bad_pool, bad_assessment)],
                alerts_path=path,
                printer=printed.append,
            )
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].pool_id, "bad")
            self.assertTrue(path.exists())
            persisted = json.loads(path.read_text())
            self.assertEqual(len(persisted), 1)
            self.assertEqual(printed and "bad" in printed[0], True)

    def test_format_alert_console_mentions_dry_run(self):
        pool = {"id": "x", "mint_a": "m1", "mint_a_symbol": "SOL", "mint_b": "m2", "mint_b_symbol": "RUG"}
        assessment = health.HealthAssessment(
            pool_id="x", score="critical", reasons=["TVL collapsed"], tvl_now=1, tvl_entry=100,
            tvl_drop_pct=0.99, volume_now=1, volume_entry=1000, snapshot_count=2,
        )
        alert = emergency.build_alert(pool, assessment)
        text = emergency.format_alert_console(alert)
        self.assertIn("EMERGENCY", text)
        self.assertIn("DRY-RUN", text)


class ScannerEmergencyIntegrationTests(unittest.TestCase):
    def test_scanner_emits_alert_when_pool_turns_critical(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.json"
            alerts_path = Path(tmp) / "alerts.json"
            # Seed history so the next scan sees a TVL crash.
            seed_history = {
                "rug-pool": {
                    "pair": "SOL/RUG",
                    "entry": {"tvl": 10_000, "volume_24h": 5000, "apr": 1500, "ts": "t0"},
                    "snapshots": [
                        {"tvl": 10_000, "volume_24h": 5000, "apr": 1500, "ts": "t0"}
                    ],
                    "last_seen": "t0",
                }
            }
            history_path.write_text(json.dumps(seed_history))

            api_response = {
                "data": {
                    "data": [
                        {
                            "id": "rug-pool",
                            "apr24h": 1500,
                            "tvl": 1000,
                            "volume24h": 2,
                            "mintA": {"symbol": "SOL", "address": "solmint"},
                            "mintB": {"symbol": "RUG", "address": "rugmint"},
                        }
                    ]
                }
            }
            config = ScannerConfig(
                min_apr=100,
                min_liquidity_usd=10,
                min_volume_24h_usd=1,
                require_sell_route=False,
                track_liquidity_health=True,
                liquidity_history_path=str(history_path),
                emergency_close_enabled=True,
                emergency_alerts_path=str(alerts_path),
            )
            with patch("raydium_lp1.scanner.fetch_json", return_value=api_response):
                report = scan(config)
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["candidates"][0]["health"]["score"], "critical")
            self.assertEqual(len(report["triggered_alerts"]), 1)
            self.assertTrue(alerts_path.exists())


if __name__ == "__main__":
    unittest.main()
