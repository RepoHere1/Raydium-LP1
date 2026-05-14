"""Tests for the Raydium-UI-parity pool filters: age and LP burn percent."""

import time
import unittest
from unittest.mock import patch

from raydium_lp1.scanner import ScannerConfig, filter_pool, normalize_pool


def _live_pool(**overrides):
    base = {
        "id": "p",
        "type": "Standard",
        "tvl": 5000,
        "feeRate": 0.04,
        "burnPercent": 100,
        "openTime": str(int(time.time()) - 6 * 3600),  # 6h old
        "day": {"apr": 1500, "volume": 1000, "volumeFee": 100},
        "mintA": {"symbol": "WSOL", "address": "sol"},
        "mintB": {"symbol": "MEME", "address": "memet"},
    }
    base.update(overrides)
    return normalize_pool(base, "apr24h")


class PoolAgeTests(unittest.TestCase):
    def test_old_pool_rejected_by_max_age(self):
        pool = _live_pool(openTime=str(int(time.time()) - 72 * 3600))  # 72h old
        config = ScannerConfig(min_apr=100, max_pool_age_hours=24)
        ok, reasons = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertTrue(any("pool age" in r and "above max" in r for r in reasons))

    def test_fresh_pool_passes_when_within_max_age(self):
        pool = _live_pool()  # 6h old
        config = ScannerConfig(min_apr=100, max_pool_age_hours=24)
        ok, reasons = filter_pool(pool, config)
        self.assertTrue(ok, reasons)

    def test_too_new_pool_rejected_by_min_age(self):
        # Pool opened 5 minutes ago, but we require >= 1 hour age.
        pool = _live_pool(openTime=str(int(time.time()) - 5 * 60))
        config = ScannerConfig(min_apr=100, min_pool_age_hours=1)
        ok, reasons = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertTrue(any("pool age" in r and "below min" in r for r in reasons))

    def test_pool_age_zero_disables_filter(self):
        pool = _live_pool(openTime="0")  # API returns 0 for some CLMM pools
        config = ScannerConfig(min_apr=100, max_pool_age_hours=24)
        ok, _ = filter_pool(pool, config)
        # openTime=0 means we have no age info -> don't reject just because of age.
        self.assertTrue(ok)


class BurnPercentTests(unittest.TestCase):
    def test_burn_below_min_rejected(self):
        pool = _live_pool(burnPercent=0)
        config = ScannerConfig(min_apr=100, min_burn_percent=100)
        ok, reasons = filter_pool(pool, config)
        self.assertFalse(ok)
        self.assertTrue(any("LP burn" in r for r in reasons))

    def test_burn_full_passes_strict_filter(self):
        pool = _live_pool(burnPercent=100)
        config = ScannerConfig(min_apr=100, min_burn_percent=100)
        ok, reasons = filter_pool(pool, config)
        self.assertTrue(ok, reasons)

    def test_partial_burn_passes_partial_filter(self):
        pool = _live_pool(burnPercent=50)
        config = ScannerConfig(min_apr=100, min_burn_percent=25)
        ok, _ = filter_pool(pool, config)
        self.assertTrue(ok)


class ConfigFromFileTests(unittest.TestCase):
    def test_new_keys_load_from_settings(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "min_apr": 100,
                "max_pool_age_hours": 12,
                "min_pool_age_hours": 1,
                "min_burn_percent": 90,
            }))
            cfg = ScannerConfig.from_file(path)
        self.assertEqual(cfg.max_pool_age_hours, 12)
        self.assertEqual(cfg.min_pool_age_hours, 1)
        self.assertEqual(cfg.min_burn_percent, 90)


if __name__ == "__main__":
    unittest.main()
