"""Regression tests for parsing the live Raydium v3 API shape.

The earlier version of normalize_pool() read flat fields like "apr24h" and
"volume24h", but the actual API returns nested objects:
    "day": {"apr": 100.5, "volume": 5000.0, "volumeFee": 200.0, "feeApr": ...},
    "openTime": "1778315822",
    "burnPercent": 100,
    ...
This file pins the new behavior so it can't silently regress.
"""

import unittest

from raydium_lp1.scanner import (
    ScannerConfig,
    filter_pool,
    normalize_pool,
    pool_apr,
    pool_fee_24h,
    pool_volume,
)


LIVE_POOL = {
    "type": "Standard",
    "programId": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    "id": "8JQvKeqa5qwtgbjUMfhVeLr5tNBEDMm8Miak2SGq2Zxw",
    "mintA": {
        "address": "So11111111111111111111111111111111111111112",
        "symbol": "WSOL",
        "name": "Wrapped SOL",
        "decimals": 9,
        "tags": [],
        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    },
    "mintB": {
        "address": "HmZWJymp357ReTz5ydxwx9f6hkhxNScxQKT6yfGDSxq8",
        "symbol": "Ollight",
        "name": "Ollight",
        "decimals": 3,
        "tags": ["community"],
        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    },
    "tvl": 1234.56,
    "feeRate": 0.04,
    "openTime": "1778315822",
    "burnPercent": 100,
    "launchMigratePool": False,
    "farmOngoingCount": 0,
    "day": {
        "volume": 3585.44,
        "volumeFee": 143.41,
        "apr": 850.23,
        "feeApr": 800.0,
        "rewardApr": [25.0, 25.23],
    },
    "week": {"apr": 600.0, "volume": 12345.0},
    "month": {"apr": 200.0, "volume": 54321.0},
    "pooltype": ["Cpmm"],
}


class LiveApiParsingTests(unittest.TestCase):
    def test_wsol_alias_to_sol(self):
        pool = normalize_pool(LIVE_POOL, "apr24h")
        self.assertEqual(pool["mint_a_symbol"], "SOL")
        self.assertEqual(pool["mint_b_symbol"], "OLLIGHT")

    def test_apr_reads_nested_day(self):
        self.assertAlmostEqual(pool_apr(LIVE_POOL, "apr24h"), 850.23)

    def test_apr_reads_nested_week(self):
        self.assertAlmostEqual(pool_apr(LIVE_POOL, "apr7d"), 600.0)

    def test_apr_falls_back_to_fee_plus_rewards(self):
        no_apr_pool = {
            "day": {"feeApr": 100, "rewardApr": [30, 20]},
            "mintA": {"symbol": "SOL"},
            "mintB": {"symbol": "X"},
        }
        self.assertEqual(pool_apr(no_apr_pool, "apr24h"), 150.0)

    def test_volume_reads_nested_day(self):
        self.assertAlmostEqual(pool_volume(LIVE_POOL, "apr24h"), 3585.44)

    def test_fee_24h_reads_nested_day(self):
        self.assertAlmostEqual(pool_fee_24h(LIVE_POOL), 143.41)

    def test_normalize_pool_extracts_new_fields(self):
        pool = normalize_pool(LIVE_POOL, "apr24h")
        self.assertAlmostEqual(pool["apr"], 850.23)
        self.assertAlmostEqual(pool["liquidity_usd"], 1234.56)
        self.assertAlmostEqual(pool["volume_24h_usd"], 3585.44)
        self.assertAlmostEqual(pool["fee_24h_usd"], 143.41)
        self.assertEqual(pool["burn_percent"], 100)
        self.assertEqual(pool["open_time"], 1778315822)
        self.assertEqual(pool["fee_rate"], 0.04)
        self.assertEqual(pool["subtypes"], ["Cpmm"])
        self.assertEqual(pool["type"], "Standard")

    def test_filter_accepts_live_wsol_pool(self):
        """The exact failure mode the user hit on Windows."""

        pool = normalize_pool(LIVE_POOL, "apr24h")
        config = ScannerConfig(
            min_apr=500,
            min_liquidity_usd=200,
            min_volume_24h_usd=50,
            allowed_quote_symbols={"SOL"},
            require_sell_route=False,
        )
        ok, reasons = filter_pool(pool, config)
        self.assertTrue(ok, reasons)


class LegacyShapeStillWorksTests(unittest.TestCase):
    def test_old_flat_shape_keeps_working(self):
        """Our existing test fixtures use a flat shape; don't break them."""

        legacy = {
            "id": "x",
            "apr24h": 1200,
            "tvl": 5000,
            "volume24h": 1000,
            "mintA": {"symbol": "SOL", "address": "a"},
            "mintB": {"symbol": "TEST", "address": "b"},
        }
        pool = normalize_pool(legacy, "apr24h")
        self.assertEqual(pool["apr"], 1200)
        self.assertEqual(pool["liquidity_usd"], 5000)
        self.assertEqual(pool["volume_24h_usd"], 1000)


if __name__ == "__main__":
    unittest.main()
