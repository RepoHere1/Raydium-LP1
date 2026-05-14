import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1 import dashboard
from raydium_lp1.scanner import ScannerConfig, scan


class DashboardBuildTests(unittest.TestCase):
    def _report(self) -> dict:
        return {
            "scanned_at": "2026-05-14T20:00:00+00:00",
            "scanned_count": 12,
            "candidate_count": 2,
            "candidate_count_pre_capacity": 5,
            "candidates_truncated": 3,
            "rejected_count": 7,
            "health_summary": {"healthy": 1, "warning": 1, "critical": 0},
            "triggered_alerts": [],
            "raydium_api_base": "https://api-v3.raydium.io",
            "candidates": [
                {
                    "id": "pool-1",
                    "mint_a_symbol": "SOL",
                    "mint_b_symbol": "TKN",
                    "apr": 1500.0,
                    "liquidity_usd": 5000.0,
                    "volume_24h_usd": 1000.0,
                    "health": {"score": "healthy", "reasons": []},
                }
            ],
            "wallet_capacity": {
                "wallet": {"address": "ADDR", "source": "env", "has_private_key": False, "private_key": ""},
                "balance": {"ok": True, "sol": 0.5, "lamports": 500_000_000, "rpc_url": "https://rpc"},
                "capacity": {"sol_balance": 0.5, "position_size_sol": 0.1, "max_positions": 4, "reserved_sol": 0.02, "available_sol": 0.48},
            },
        }

    def test_build_dashboard_populates_fields(self):
        config = ScannerConfig(strategy="aggressive", position_size_sol=0.1)
        with tempfile.TemporaryDirectory() as tmp:
            alerts_path = Path(tmp) / "alerts.json"
            alerts_path.write_text(json.dumps([
                {"timestamp": "t1", "severity": "critical", "pool_id": "p1", "pair": "SOL/RUG"}
            ]))
            data = dashboard.build_dashboard(
                config=config, report=self._report(), alerts_path=alerts_path,
                rpc_health=[{"url": "https://rpc", "ok": True}],
            )
        self.assertEqual(data.settings["strategy"], "aggressive")
        self.assertEqual(len(data.open_positions), 1)
        self.assertEqual(data.open_positions[0]["pair"], "SOL/TKN")
        self.assertEqual(len(data.recent_alerts), 1)
        self.assertEqual(data.last_scan["candidates_truncated"], 3)
        self.assertEqual(data.wallet_capacity["capacity"]["max_positions"], 4)
        self.assertEqual(data.rpc_health[0]["ok"], True)

    def test_render_text_has_expected_sections(self):
        config = ScannerConfig()
        data = dashboard.build_dashboard(config=config, report=self._report(),
                                         alerts_path=Path("/nonexistent/none.json"))
        text = dashboard.render_dashboard_text(data)
        for section in ("Settings", "Wallet & capacity", "Open positions", "Recent alerts", "RPC health", "Last scan"):
            self.assertIn(section, text)
        self.assertIn("SOL/TKN", text)

    def test_write_dashboard_creates_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dash.json"
            data = dashboard.build_dashboard(
                config=ScannerConfig(), report=self._report(),
                alerts_path=Path("/nope/none.json"),
            )
            dashboard.write_dashboard(data, path)
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text())
            self.assertIn("settings", payload)
            self.assertIn("wallet_capacity", payload)
            self.assertIn("open_positions", payload)


class ScannerDashboardIntegrationTests(unittest.TestCase):
    def test_main_writes_dashboard_when_flag_set(self):
        api_response = {
            "data": {"data": [{
                "id": "pool-1",
                "apr24h": 1500, "tvl": 5000, "volume24h": 1000,
                "mintA": {"symbol": "SOL", "address": "solmint"},
                "mintB": {"symbol": "TKN", "address": "tknmint"},
            }]}
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "settings.json"
            history_path = Path(tmp) / "history.json"
            alerts_path = Path(tmp) / "alerts.json"
            dashboard_path = Path(tmp) / "dashboard.json"
            config_path.write_text(json.dumps({
                "dry_run": True,
                "strategy": "custom",
                "min_apr": 100,
                "min_liquidity_usd": 10,
                "min_volume_24h_usd": 10,
                "require_sell_route": False,
                "track_liquidity_health": True,
                "emergency_close_enabled": True,
                "position_size_sol": 0.1,
                "reserve_sol": 0.0,
                "liquidity_history_path": str(history_path),
                "emergency_alerts_path": str(alerts_path),
            }))

            from raydium_lp1 import scanner
            with patch("raydium_lp1.scanner.fetch_json", return_value=api_response), \
                 patch("raydium_lp1.dashboard.DEFAULT_DASHBOARD_PATH", dashboard_path), \
                 patch.object(scanner, "DEFAULT_CONFIG_PATH", config_path):
                # write_dashboard uses the path we pass; main uses default constant
                with patch("raydium_lp1.dashboard.write_dashboard") as wd:
                    captured = {}
                    def fake_write(data, *args, **kwargs):
                        captured["data"] = data
                    wd.side_effect = fake_write
                    rc = scanner.main(["--config", str(config_path), "--dashboard"])
                self.assertEqual(rc, 0)
                self.assertIn("data", captured)
                rendered = dashboard.render_dashboard_text(captured["data"])
                self.assertIn("Raydium-LP1 Dashboard", rendered)


if __name__ == "__main__":
    unittest.main()
