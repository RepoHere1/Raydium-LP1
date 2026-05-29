"""Tests for tune_advisor patch building."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from raydium_lp1.tune_advisor import _pressure_to_patch, _trade_ready_bundle


class TuneAdvisorTests(unittest.TestCase):
    def test_pressure_sort_field_liquidity(self):
        cfg = MagicMock()
        cfg.apr_field = "apr24h"
        cfg.min_apr = 350.0
        p = {"setting_key": "pool_sort_field", "direction": "align_with_apr_feed"}
        patch = _pressure_to_patch(p, cfg)
        self.assertEqual(patch.get("pool_sort_field"), "liquidity")
        self.assertEqual(patch.get("sort_type"), "desc")

    def test_trade_ready_bundle_has_clmm_sort(self):
        cfg = MagicMock()
        cfg.pages = 1
        cfg.min_apr = 350.0
        cfg.min_liquidity_usd = 750.0
        cfg.hard_exit_min_tvl_usd = 125.0
        cfg.min_volume_24h_usd = 2000.0
        bundle = _trade_ready_bundle(cfg, {"candidate_count": 0})
        self.assertEqual(bundle["settings_patch"].get("pool_type"), "concentrated")
        self.assertEqual(bundle["settings_patch"].get("pool_sort_field"), "liquidity")


if __name__ == "__main__":
    unittest.main()
