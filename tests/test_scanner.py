import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1.scanner import (
    ScannerConfig,
    extract_pool_items,
    filter_pool,
    hot_reload_scanner_config,
    load_dotenv,
    normalize_pool,
    pool_list_url,
    write_reports,
)


class ScannerTests(unittest.TestCase):
    def test_extracts_nested_pool_list(self):
        response = {"success": True, "data": {"count": 1, "data": [{"id": "pool-1"}]}}
        self.assertEqual(extract_pool_items(response), [{"id": "pool-1"}])

    def test_default_apr_threshold_is_999_99(self):
        self.assertEqual(ScannerConfig().min_apr, 999.99)

    def test_candidate_passes_filters(self):
        config = ScannerConfig(min_apr=999.99, min_liquidity_usd=1_000, min_volume_24h_usd=100)
        pool = normalize_pool(
            {
                "id": "pool-1",
                "apr24h": 1_200,
                "tvl": 2_500,
                "volume24h": 500,
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "TEST", "address": "test-mint"},
            },
            "apr24h",
        )
        ok, reasons = filter_pool(pool, config)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_low_liquidity_rejected(self):
        config = ScannerConfig(min_apr=999.99, min_liquidity_usd=1_000, min_volume_24h_usd=100)
        pool = normalize_pool(
            {
                "id": "pool-1",
                "apr24h": 1_200,
                "tvl": 10,
                "volume24h": 500,
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "TEST", "address": "test-mint"},
            },
            "apr24h",
        )
        ok, reasons = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertIn("liquidity $10.00 below $1000.00", reasons)

    def test_url_uses_apr_sort(self):
        config = ScannerConfig(page_size=10, apr_field="apr24h")
        url = pool_list_url(config, page=2)
        self.assertIn("poolSortField=apr24h", url)
        self.assertIn("pageSize=10", url)
        self.assertIn("page=2", url)

    def test_load_dotenv_and_config_rpc_urls(self):
        with tempfile.TemporaryDirectory() as tempdir:
            env_path = Path(tempdir) / ".env"
            config_path = Path(tempdir) / "settings.json"
            env_path.write_text(
                "SOLANA_RPC_URL=https://api.mainnet-beta.solana.com\n"
                "SOLANA_RPC_URLS=https://solana-rpc.publicnode.com,https://solana.drpc.org\n",
                encoding="utf-8",
            )
            config_path.write_text('{"min_apr": 999.99, "solana_rpc_urls": ["https://extra.example"]}', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_dotenv(env_path)
                config = ScannerConfig.from_file(config_path)
            self.assertEqual(config.solana_rpc_urls[0], "https://api.mainnet-beta.solana.com")
            self.assertIn("https://solana-rpc.publicnode.com", config.solana_rpc_urls)
            self.assertIn("https://extra.example", config.solana_rpc_urls)

    def test_write_reports_creates_json_and_csv(self):
        report = {
            "scanned_at": "2026-05-13T00:00:00+00:00",
            "candidates": [
                {
                    "id": "pool-1",
                    "mint_a_symbol": "SOL",
                    "mint_b_symbol": "TEST",
                    "apr": 1200.0,
                    "liquidity_usd": 2500.0,
                    "volume_24h_usd": 500.0,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            write_reports(report, Path(tempdir))
            self.assertTrue((Path(tempdir) / "latest.json").exists())
            self.assertTrue((Path(tempdir) / "candidates.csv").exists())


    def test_hot_reload_picks_up_json_edit(self):
        import json
        import time

        with tempfile.TemporaryDirectory() as tempdir:
            p = Path(tempdir) / "settings.json"
            raw = {
                "dry_run": True,
                "network": "solana",
                "solana_rpc_urls": [],
                "min_apr": 500.0,
                "min_liquidity_usd": 200.0,
                "min_volume_24h_usd": 50.0,
            }
            p.write_text(json.dumps(raw), encoding="utf-8")
            ScannerConfig.from_file(p)
            anchor = [p.stat().st_mtime]
            self.assertIsNone(hot_reload_scanner_config(p, anchor))
            time.sleep(0.05)
            raw["min_liquidity_usd"] = 50.0
            p.write_text(json.dumps(raw), encoding="utf-8")
            cfg1 = hot_reload_scanner_config(p, anchor)
            self.assertIsNotNone(cfg1)
            self.assertEqual(cfg1.min_liquidity_usd, 50.0)


if __name__ == "__main__":
    unittest.main()
