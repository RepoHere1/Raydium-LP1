"""Tests for trade_activity scaffolding."""

from __future__ import annotations

import unittest

from raydium_lp1 import trade_activity


class TradeActivityTests(unittest.TestCase):
    def test_open_close_dicts(self):
        pool = {"id": "x", "mint_a_symbol": "SOL", "mint_b_symbol": "Z", "mint_b": "mintz"}
        o = trade_activity.describe_open_lp_dry_run(pool, notion_sol=0.2)
        c = trade_activity.describe_close_lp_dry_run(pool)
        self.assertEqual(o["phase"], "would_open_lp")
        self.assertEqual(c["phase"], "would_close_lp")
        self.assertTrue(o["dry_run"])


if __name__ == "__main__":
    unittest.main()
