import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1.scanner import (
    ScannerConfig,
    extract_pool_items,
    filter_pool,
    load_dotenv,
    normalize_pool,
    pool_list_url,
    raydium_pool_sort_param,
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

    def test_pool_sort_field_overrides_raydium_sort_only(self):
        config = ScannerConfig(page_size=10, apr_field="apr24h", pool_sort_field="volume24h")
        self.assertEqual(raydium_pool_sort_param(config), "volume24h")
        url = pool_list_url(config, page=1)
        self.assertIn("poolSortField=volume24h", url)

    def test_hard_exit_rejects_micro_tvl_first(self):
        config = ScannerConfig(
            min_apr=50.0,
            hard_exit_min_tvl_usd=1000.0,
            min_liquidity_usd=100.0,
            min_volume_24h_usd=1.0,
        )
        pool = normalize_pool(
            {
                "id": "pool-1",
                "apr24h": 500,
                "tvl": 5,
                "volume24h": 500_000,
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "TEST", "address": "test-mint"},
            },
            "apr24h",
        )
        ok, reasons = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertTrue(reasons[0].startswith("HARD reject: TVL"))

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

    def test_junk_solana_rpc_urls_in_json_are_dropped(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "settings.json"
            config_path.write_text(
                json.dumps(
                    {
                        "min_apr": 999.99,
                        "solana_rpc_urls": ["https://extra.example", "y", "ftp://bad/x"],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = ScannerConfig.from_file(config_path)
        self.assertIn("https://extra.example", config.solana_rpc_urls)
        self.assertNotIn("y", config.solana_rpc_urls)
        self.assertTrue(all(str(u).startswith("http") for u in config.solana_rpc_urls))

    def test_env_comma_list_drops_invalid_tail_tokens(self):
        with tempfile.TemporaryDirectory() as tempdir:
            env_path = Path(tempdir) / ".env"
            config_path = Path(tempdir) / "settings.json"
            env_path.write_text(
                "SOLANA_RPC_URL=https://good.example/rpc\n"
                "SOLANA_RPC_URLS=https://a.example.com,y\n",
                encoding="utf-8",
            )
            config_path.write_text('{"min_apr": 999.99}', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_dotenv(env_path)
                config = ScannerConfig.from_file(config_path)
        self.assertEqual(config.solana_rpc_urls[0], "https://good.example/rpc")
        self.assertIn("https://a.example.com", config.solana_rpc_urls)
        self.assertNotIn("y", config.solana_rpc_urls)

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
