import unittest
from unittest.mock import patch

from raydium_lp1 import routes
from raydium_lp1.scanner import ScannerConfig, normalize_pool, scan


def _fake_fetch(url: str) -> dict:
    """Stub HTTP fetcher: success when the URL contains 'GOOD', else block."""

    if "BLOCK" in url:
        return {"error": "no route"}
    if "EMPTY" in url:
        return {}
    return {"data": {"outAmount": 12345, "routePlan": [{"swapInfo": {"label": "x"}}]}}


class RouteCheckerTests(unittest.TestCase):
    def test_jupiter_route_ok_when_payload_priced(self):
        out = routes.check_jupiter_route("GOODMINT", routes.USDC_MINT, fetcher=_fake_fetch)
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "jupiter")
        self.assertEqual(out["out_amount"], 12345)

    def test_jupiter_route_blocked_when_error(self):
        out = routes.check_jupiter_route("BLOCKMINT", routes.USDC_MINT, fetcher=_fake_fetch)
        self.assertFalse(out["ok"])

    def test_raydium_route_ok(self):
        out = routes.check_raydium_route("GOODMINT", routes.USDC_MINT, fetcher=_fake_fetch)
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "raydium")

    def test_base_token_is_trivially_sellable(self):
        result = routes.check_sell_route("any-mint", "SOL", fetcher=_fake_fetch)
        self.assertTrue(result.ok)
        self.assertEqual(result.best_source, "base-token")

    def test_check_sell_route_records_all_sources(self):
        result = routes.check_sell_route(
            "GOODMINT",
            "TEST",
            base_symbols=("SOL",),
            sources=("jupiter", "raydium"),
            fetcher=_fake_fetch,
        )
        self.assertTrue(result.ok)
        # Two sources x one base = up to two records.
        source_names = {entry["source"] for entry in result.sources}
        self.assertEqual(source_names, {"jupiter", "raydium"})
        self.assertIsNotNone(result.best_source)

    def test_check_sell_route_blocks_when_all_sources_fail(self):
        result = routes.check_sell_route(
            "BLOCKMINT",
            "RUG",
            base_symbols=("SOL", "USDC"),
            sources=("jupiter", "raydium"),
            fetcher=_fake_fetch,
        )
        self.assertFalse(result.ok)
        # We tried 2 bases x 2 sources = 4 records.
        self.assertEqual(len(result.sources), 4)

    def test_pool_sellability_blocks_when_token_b_unroutable(self):
        pool = {
            "mint_a": "GOODMINT1",
            "mint_a_symbol": "SOL",
            "mint_b": "BLOCKMINT",
            "mint_b_symbol": "RUG",
        }
        result = routes.check_pool_sellability(pool, fetcher=_fake_fetch)
        self.assertFalse(result.ok)
        self.assertTrue(any("token B" in r for r in result.reasons))

    def test_format_sellability_log_contains_sources(self):
        pool = {
            "mint_a": "any",
            "mint_a_symbol": "SOL",
            "mint_b": "GOODMINT",
            "mint_b_symbol": "TEST",
        }
        result = routes.check_pool_sellability(pool, fetcher=_fake_fetch)
        log = routes.format_sellability_log(result)
        self.assertIn("sellability", log)
        self.assertIn("jupiter", log)
        self.assertIn("raydium", log)


class ScannerSellabilityIntegrationTests(unittest.TestCase):
    def _config(self) -> ScannerConfig:
        return ScannerConfig(
            min_apr=100,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            require_sell_route=True,
        )

    def _pool_payload(self, pool_id: str, symbol_b: str, mint_b: str) -> dict:
        return {
            "id": pool_id,
            "apr24h": 1500,
            "tvl": 5000,
            "volume24h": 1000,
            "mintA": {"symbol": "SOL", "address": "sol-mint"},
            "mintB": {"symbol": symbol_b, "address": mint_b},
        }

    def test_scanner_rejects_unsellable_pool(self):
        config = self._config()
        api_response = {
            "data": {
                "data": [
                    self._pool_payload("good-pool", "TEST", "GOODMINT"),
                    self._pool_payload("bad-pool", "RUG", "BLOCKMINT"),
                ]
            }
        }
        with patch("raydium_lp1.scanner.fetch_json", return_value=api_response):
            def checker(pool):
                return routes.check_pool_sellability(
                    pool, base_symbols=("SOL",), sources=("jupiter",), fetcher=_fake_fetch
                )

            report = scan(config, sellability_checker=checker)
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["candidates"][0]["id"], "good-pool")
        self.assertEqual(report["rejected_count"], 1)
        self.assertEqual(report["rejected_preview"][0]["id"], "bad-pool")

    def test_scanner_passes_through_when_sell_route_check_disabled(self):
        config = ScannerConfig(
            min_apr=100,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            require_sell_route=False,
        )
        api_response = {
            "data": {"data": [self._pool_payload("bad-pool", "RUG", "BLOCKMINT")]}
        }
        with patch("raydium_lp1.scanner.fetch_json", return_value=api_response):
            report = scan(config)
        self.assertEqual(report["candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
