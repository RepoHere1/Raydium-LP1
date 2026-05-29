"""Tests for low-APR / high-cash pool anomaly detection."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from raydium_lp1.cash_anomalies import (
    build_cash_anomaly_report,
    exit_liquidity_floor_usd,
    format_terminal_block,
    pool_exit_eligible,
)
from raydium_lp1.scanner import RAYDIUM_CLMM_PROGRAM_ID


def _pool(**kw) -> dict:
    base = {
        "id": "Pool111",
        "program_id": RAYDIUM_CLMM_PROGRAM_ID,
        "mint_a_symbol": "SOL",
        "mint_b_symbol": "MEME",
        "liquidity_usd": 50_000.0,
        "volume_24h_usd": 120_000.0,
        "fee_24h_usd": 80.0,
        "apr": 45.0,
    }
    base.update(kw)
    return base


class TestCashAnomalies(unittest.TestCase):
    def test_exit_floor_prefers_hard_exit(self):
        cfg = SimpleNamespace(hard_exit_min_tvl_usd=1000.0, min_liquidity_usd=500.0)
        self.assertEqual(exit_liquidity_floor_usd(cfg), 1000.0)

    def test_pool_exit_eligible_requires_clmm_and_tvl(self):
        cfg = SimpleNamespace(hard_exit_min_tvl_usd=1000.0, min_liquidity_usd=500.0)
        floor = exit_liquidity_floor_usd(cfg)
        self.assertTrue(pool_exit_eligible(_pool(liquidity_usd=5000), floor))
        self.assertFalse(pool_exit_eligible(_pool(liquidity_usd=100), floor))
        self.assertFalse(
            pool_exit_eligible(_pool(program_id="OtherProg", liquidity_usd=5000), floor)
        )

    def test_detects_low_apr_high_cash(self):
        cfg = SimpleNamespace(
            hard_exit_min_tvl_usd=1000.0,
            min_liquidity_usd=500.0,
            min_apr=200.0,
            cash_anomaly_enabled=True,
            cash_anomaly_min_fee_usd=25.0,
            cash_anomaly_max_apr=150.0,
            cash_anomaly_top_n=10,
            cash_anomaly_implied_gap_min=10.0,
        )
        report = build_cash_anomaly_report([_pool(apr=45.0, fee_24h_usd=120.0)], cfg)
        self.assertEqual(report["anomaly_count"], 1)
        row = report["rows"][0]
        self.assertEqual(row["cash_24h_usd"], 120.0)
        self.assertIn("low_apr_high_cash", row["anomaly_tags"])
        self.assertIn("below_scanner_min_apr", row["anomaly_tags"])

    def test_skips_high_apr_unless_implied_gap(self):
        cfg = SimpleNamespace(
            hard_exit_min_tvl_usd=0.0,
            min_liquidity_usd=1000.0,
            min_apr=50.0,
            cash_anomaly_enabled=True,
            cash_anomaly_min_fee_usd=25.0,
            cash_anomaly_max_apr=150.0,
            cash_anomaly_top_n=10,
            cash_anomaly_implied_gap_min=10.0,
        )
        # High reported APR, modest fees — not an anomaly.
        report = build_cash_anomaly_report(
            [_pool(apr=900.0, fee_24h_usd=30.0, liquidity_usd=200_000.0)],
            cfg,
        )
        self.assertEqual(report["anomaly_count"], 0)

    def test_terminal_block_includes_pool_id(self):
        cfg = SimpleNamespace(
            hard_exit_min_tvl_usd=1000.0,
            min_liquidity_usd=500.0,
            min_apr=200.0,
            cash_anomaly_enabled=True,
            cash_anomaly_min_fee_usd=25.0,
            cash_anomaly_max_apr=150.0,
            cash_anomaly_top_n=10,
            cash_anomaly_implied_gap_min=10.0,
        )
        report = build_cash_anomaly_report([_pool()], cfg, candidate_ids={"Pool111"})
        lines = format_terminal_block(report)
        joined = "\n".join(lines)
        self.assertIn("ANOMALIES", joined)
        self.assertIn("Pool111", joined)
        self.assertIn("CASH", joined)


if __name__ == "__main__":
    unittest.main()
