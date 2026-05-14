import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1.fee_apr_floor import FeeAprFloorConfig
from raydium_lp1.honeypot_guard import HoneypotGuardConfig
from raydium_lp1.lp_lock_guard import LpLockGuardConfig
from raydium_lp1.mint_authority_guard import MintAuthorityGuardConfig
from raydium_lp1.pool_age_guard import PoolAgeGuardConfig
from raydium_lp1.price_impact_guard import PriceImpactGuardConfig
from raydium_lp1.quote_only_entry import QuoteOnlyEntryConfig
from raydium_lp1.rpc_health_gate import RpcHealthGateConfig
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
from raydium_lp1.survival_runway import SurvivalRunwayConfig


def _bare_config(**overrides) -> ScannerConfig:
    """ScannerConfig with all strategy filters disabled, for legacy filter tests."""
    base = dict(
        min_apr=999.99,
        min_liquidity_usd=1_000,
        min_volume_24h_usd=100,
        survival_runway=SurvivalRunwayConfig(enabled=False),
        quote_only_entry=QuoteOnlyEntryConfig(enabled=False),
        honeypot_guard=HoneypotGuardConfig(enabled=False),
        pool_age_guard=PoolAgeGuardConfig(enabled=False),
        mint_authority_guard=MintAuthorityGuardConfig(enabled=False),
        lp_lock_guard=LpLockGuardConfig(enabled=False),
        price_impact_guard=PriceImpactGuardConfig(enabled=False),
        fee_apr_floor=FeeAprFloorConfig(enabled=False),
        rpc_health_gate=RpcHealthGateConfig(enabled=False),
    )
    base.update(overrides)
    return ScannerConfig(**base)


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
        config = _bare_config()
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
        config = _bare_config(min_apr=500.0)
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
        config = _bare_config()
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

    def test_survival_runway_rejects_thin_pool_and_categorizes_it(self):
        config = _bare_config(
            min_apr=100.0,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            max_position_usd=25.0,
            survival_runway=SurvivalRunwayConfig(
                enabled=True,
                min_tvl_multiple_of_position=200,
                min_daily_volume_pct_of_tvl=5.0,
                require_active_week=False,
            ),
        )
        pool = normalize_pool(
            {
                "id": "tiny",
                "apr24h": 9_000,
                "tvl": 1_000,
                "volume24h": 500,
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "MEME", "address": "meme-mint"},
            },
            "apr24h",
        )
        ok, reasons, categories = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertIn("survival_runway_failed", categories)
        self.assertTrue(any("survival_runway" in r for r in reasons))

    def test_quote_only_entry_rejects_unknown_unknown_pair(self):
        config = _bare_config(
            min_apr=100.0,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            allowed_quote_symbols=set(),
            quote_only_entry=QuoteOnlyEntryConfig(
                enabled=True,
                allowed_quote_symbols=frozenset({"SOL", "USDC", "USDT", "USD1"}),
            ),
        )
        pool = normalize_pool(
            {
                "id": "unknown",
                "apr24h": 9_000,
                "tvl": 1_000_000,
                "volume24h": 500_000,
                "mintA": {"symbol": "ABC", "address": "abc-mint"},
                "mintB": {"symbol": "DEF", "address": "def-mint"},
            },
            "apr24h",
        )
        ok, reasons, categories = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertIn("quote_only_entry_failed", categories)
        self.assertTrue(any("quote_only_entry" in r for r in reasons))

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

    def test_pool_age_guard_rejects_unknown_age_pool(self):
        config = _bare_config(
            min_apr=100.0,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            pool_age_guard=PoolAgeGuardConfig(enabled=True, min_age_minutes=60),
        )
        pool = normalize_pool(
            {
                "id": "fresh",
                "apr24h": 9_000,
                "tvl": 1_000_000,
                "volume24h": 50_000,
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "TEST", "address": "test-mint"},
            },
            "apr24h",
        )
        ok, reasons, categories = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertIn("pool_age_guard_failed", categories)
        self.assertTrue(any("pool_age_guard" in r for r in reasons))

    def test_price_impact_guard_rejects_tiny_pool(self):
        config = _bare_config(
            min_apr=100.0,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            max_position_usd=25.0,
            price_impact_guard=PriceImpactGuardConfig(enabled=True, max_impact_percent=1.0),
        )
        pool = normalize_pool(
            {
                "id": "tiny",
                "apr24h": 9_000,
                "tvl": 50,
                "volume24h": 25,
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "TEST", "address": "test-mint"},
            },
            "apr24h",
        )
        ok, _reasons, categories = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertIn("price_impact_guard_failed", categories)

    def test_fee_apr_floor_rejects_reward_only_pool(self):
        config = _bare_config(
            min_apr=100.0,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            fee_apr_floor=FeeAprFloorConfig(enabled=True, min_fee_apr_percent=30.0),
        )
        pool = normalize_pool(
            {
                "id": "reward-only",
                "apr24h": 9_000,
                "tvl": 1_000_000,
                "volume24h": 5_000,
                "fee24h": 1,
                "mintA": {"symbol": "SOL", "address": "sol-mint"},
                "mintB": {"symbol": "TEST", "address": "test-mint"},
            },
            "apr24h",
        )
        ok, _reasons, categories = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertIn("fee_apr_floor_failed", categories)

    def test_active_filters_block_contains_all_nine(self):
        from raydium_lp1.scanner import scan
        from unittest.mock import patch

        config = _bare_config()
        with patch("raydium_lp1.scanner.fetch_json", return_value={"data": {"data": []}}):
            report = scan(config)
        active = report["active_filters"]
        self.assertEqual(
            set(active.keys()),
            {
                "survival_runway",
                "quote_only_entry",
                "honeypot_guard",
                "pool_age_guard",
                "mint_authority_guard",
                "lp_lock_guard",
                "price_impact_guard",
                "fee_apr_floor",
                "rpc_health_gate",
            },
        )

    def test_reason_categories_include_all_nine(self):
        from raydium_lp1.scanner import REASON_CATEGORIES

        for needed in (
            "survival_runway_failed",
            "quote_only_entry_failed",
            "honeypot_guard_failed",
            "pool_age_guard_failed",
            "mint_authority_guard_failed",
            "lp_lock_guard_failed",
            "price_impact_guard_failed",
            "fee_apr_floor_failed",
        ):
            self.assertIn(needed, REASON_CATEGORIES)

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
