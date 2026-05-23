import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1.scanner import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    MAX_PAGES_HARD_CEILING,
    MAX_PAGE_SIZE,
    ScannerConfig,
    _clamp_page_size,
    _clamp_pages,
    scan,
)


class ClampingTests(unittest.TestCase):
    def test_pages_clamped_to_ceiling(self):
        self.assertEqual(_clamp_pages(5000), MAX_PAGES_HARD_CEILING)
        self.assertEqual(_clamp_pages(MAX_PAGES_HARD_CEILING + 1), MAX_PAGES_HARD_CEILING)

    def test_pages_clamped_to_at_least_one(self):
        self.assertEqual(_clamp_pages(0), 1)
        self.assertEqual(_clamp_pages(-3), 1)

    def test_page_size_clamped(self):
        self.assertEqual(_clamp_page_size(99999), MAX_PAGE_SIZE)
        self.assertEqual(_clamp_page_size(1), 10)
        self.assertEqual(_clamp_page_size(250), 250)

    def test_config_file_load_clamps_dangerous_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"pages": 9999, "page_size": 99999, "min_apr": 100}))
            config = ScannerConfig.from_file(path)
        self.assertEqual(config.pages, MAX_PAGES_HARD_CEILING)
        self.assertEqual(config.page_size, MAX_PAGE_SIZE)

    def test_config_defaults_for_new_fields(self):
        cfg = ScannerConfig()
        self.assertEqual(cfg.http_timeout_seconds, DEFAULT_HTTP_TIMEOUT_SECONDS)
        self.assertGreaterEqual(cfg.page_delay_seconds, 0.0)


class ScanProgressTests(unittest.TestCase):
    def test_scan_logs_progress_per_page(self):
        api_response = {"data": {"data": []}}
        config = ScannerConfig(
            min_apr=100, min_liquidity_usd=10, min_volume_24h_usd=10,
            require_sell_route=False, track_liquidity_health=False,
            pages=3, page_delay_seconds=0.0,
        )
        captured = io.StringIO()
        with patch("raydium_lp1.scanner.fetch_json", return_value=api_response), \
             patch("sys.stderr", captured):
            scan(config)
        log = captured.getvalue()
        self.assertIn("page 1/3", log)
        self.assertIn("page 2/3", log)
        self.assertIn("page 3/3", log)

    def test_scan_passes_timeout_to_fetch(self):
        seen = {}

        def fake_fetch(url, timeout=999):
            seen["timeout"] = timeout
            return {"data": {"data": []}}

        config = ScannerConfig(
            min_apr=100, require_sell_route=False, track_liquidity_health=False,
            http_timeout_seconds=7, page_delay_seconds=0.0,
        )
        with patch("raydium_lp1.scanner.fetch_json", side_effect=fake_fetch):
            scan(config)
        self.assertEqual(seen["timeout"], 7)

    def test_scan_skips_failed_page_and_continues(self):
        api_response = {"data": {"data": []}}
        config = ScannerConfig(
            min_apr=100,
            require_sell_route=False,
            track_liquidity_health=False,
            pages=2,
            page_delay_seconds=0.0,
        )
        captured = io.StringIO()

        def fake_fetch(url, timeout=15):
            if "page=1" in url or "page%3D1" in url:
                raise RuntimeError("ssl read failed")
            return api_response

        with patch("raydium_lp1.scanner.fetch_json", side_effect=fake_fetch), patch(
            "sys.stderr", captured
        ):
            report = scan(config)
        self.assertEqual(report["pages_failed"], 1)
        self.assertIn("page 1/2 FAILED", captured.getvalue())
        self.assertIn("page 2/2", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
