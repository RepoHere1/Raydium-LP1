import tempfile
import unittest
from pathlib import Path

from raydium_lp1 import dashboard_web


class DashboardWebPageTests(unittest.TestCase):
    def test_module_imports_and_page_has_shell(self):
        page = dashboard_web._page().decode("utf-8")
        self.assertNotIn("BOOT_JSON", page)
        self.assertNotIn("CLIENT_JS_HERE", page)
        self.assertIn("Raydium-LP1 · mission control", page)
        self.assertIn("form_sections", page)
        self.assertIn("Save settings", page)
        self.assertIn("row2", page)
        self.assertIn("--bg:#000", page)
        self.assertIn("border:3px solid var(--yellow)", page)
        self.assertIn("Recent alerts", page)
        self.assertIn("CRITICAL", page)
        self.assertIn("Candidates", page)
        self.assertIn("Pool + token mints", page)
        self.assertIn("addr-full", page)
        self.assertIn("poolAddressesHtml", page)
        self.assertIn("SOL/WSOL mint hidden", page)
        self.assertIn("TRADING MODE", page)
        self.assertIn("mode-live", page)
        self.assertIn("TUNING", page)
        self.assertIn("tuning-panel", page)
        self.assertIn("addr-row", page)
        self.assertIn("setTuningUi", page)
        self.assertIn("feedNote", page)
        self.assertIn("schedulePoll", page)


class DashboardWebStatusTests(unittest.TestCase):
    def test_dashboard_stale_when_settings_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = tmp_path / "settings.json"
            dash = tmp_path / "dashboard.json"
            settings.write_text('{"min_apr": 1}\n', encoding="utf-8")
            dash.write_text('{"generated_at": "t"}\n', encoding="utf-8")
            import os
            import time

            old = time.time() - 30
            os.utime(dash, (old, old))
            paths = dashboard_web.WebPaths(dashboard_path=dash, settings_path=settings)
            self.assertTrue(dashboard_web._dashboard_stale(paths))

    def test_status_flags_invalid_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = tmp_path / "settings.json"
            settings.write_text("<<<<<<< conflict\n", encoding="utf-8")
            paths = dashboard_web.WebPaths(
                dashboard_path=tmp_path / "missing.json",
                settings_path=settings,
            )
            st = dashboard_web._status_payload(paths)
            self.assertFalse(st["settings_valid"])
            self.assertIn("conflict", (st["settings_error"] or "").lower())


class DashboardWebDriftTests(unittest.TestCase):
    def test_drift_keys_when_min_apr_differs(self):
        snap = {"min_apr": 1, "min_liquidity_usd": 2000}
        disk = {"min_apr": 350, "min_liquidity_usd": 2000}
        keys = dashboard_web._settings_drift_keys(snap, disk)
        self.assertIn("min_apr", keys)
        self.assertNotIn("min_liquidity_usd", keys)

    def test_save_warnings_high_min_apr(self):
        warns = dashboard_web._settings_save_warnings({"min_apr": 350, "require_sell_route": False})
        self.assertTrue(any("min_apr=350" in w for w in warns))

    def test_snapshot_from_dashboard_blob(self):
        blob = {"generated_at": "t", "settings": {"min_apr": 1, "pool_sort_field": "liquidity"}}
        snap = dashboard_web._snapshot_settings_from_dashboard(blob)
        self.assertEqual(snap["min_apr"], 1)
        self.assertEqual(snap["pool_sort_field"], "liquidity")


if __name__ == "__main__":
    unittest.main()
