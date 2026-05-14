import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1.scanner import (
    ScannerConfig,
    apr_field_window,
    extract_pool_items,
    filter_pool,
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

    def test_apr_field_window_mapping(self):
        self.assertEqual(apr_field_window("apr24h"), "day")
        self.assertEqual(apr_field_window("aprWeek"), "week")
        self.assertEqual(apr_field_window("aprMonth"), "month")

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
        ok, reasons, categories = filter_pool(pool, config)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])
        self.assertEqual(categories, [])

    def test_nested_day_window_payload_is_parsed(self):
        """Current Raydium API: apr24h is None at top level; real APR lives under `day.apr`."""
        config = ScannerConfig(min_apr=500.0, min_liquidity_usd=1_000, min_volume_24h_usd=100)
        pool = normalize_pool(
            {
                "id": "pool-2",
                "apr24h": None,
                "tvl": 2_500,
                "day": {"apr": 1_234.5, "volume": 800, "volumeFee": 12.5},
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "TEST", "address": "test-mint"},
            },
            "apr24h",
        )
        self.assertAlmostEqual(pool["apr"], 1_234.5)
        self.assertAlmostEqual(pool["volume_24h_usd"], 800)
        self.assertAlmostEqual(pool["fee_24h_usd"], 12.5)
        ok, _reasons, categories = filter_pool(pool, config)
        self.assertTrue(ok)
        self.assertEqual(categories, [])

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
        ok, reasons, categories = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertIn("liquidity $10.00 below $1000.00", reasons)
        self.assertIn("liquidity_below_threshold", categories)

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


if __name__ == "__main__":
    unittest.main()
