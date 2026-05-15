"""Unit tests for dial_in_analyst (post-scan tuning hints)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from raydium_lp1 import dial_in_analyst, verdicts
from raydium_lp1.scanner import ScannerConfig


def _make_config(data: dict) -> ScannerConfig:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "c.json"
        merged = {
            "dry_run": True,
            "network": "solana",
            "strategy": "custom",
            "min_apr": 500.0,
            "min_liquidity_usd": 2000.0,
            "min_volume_24h_usd": 100.0,
            "hard_exit_min_tvl_usd": 0.0,
            "max_route_price_impact_pct": 30.0,
            "require_sell_route": True,
            "solana_rpc_urls": [],
        }
        merged.update(data)
        p.write_text(json.dumps(merged), encoding="utf-8")
        return ScannerConfig.from_file(p)


class DialInAnalystTests(unittest.TestCase):
    def test_tvl_driver_produces_liquidity_pressure(self):
        cfg = _make_config({"min_liquidity_usd": 5000.0})
        report = {
            "scanned_count": 1000,
            "candidate_count": 0,
            "rejected_count": 1000,
            "rejection_breakdown": {"tvl_below_threshold": 900, "apr_below_threshold": 100},
            "rejection_reason_histogram": {"liquidity $1.00 below $5000.00": 900},
            "wallet_capacity": {"capacity": {"max_positions": 5}, "balance": {"sol": 10.0}},
        }
        d = dial_in_analyst.build_scan_diagnosis(cfg, report)
        keys = [p["setting_key"] for p in d["setting_pressure"]]
        self.assertIn("min_liquidity_usd", keys)
        self.assertEqual(d["bottleneck_shape"], "single_dominant_gate")

    def test_coherence_hard_exit_above_min_liquidity(self):
        cfg = _make_config({"min_liquidity_usd": 200.0, "hard_exit_min_tvl_usd": 800.0})
        report = {
            "scanned_count": 10,
            "candidate_count": 0,
            "rejected_count": 10,
            "rejection_breakdown": {"hard_exit_red_line": 10},
        }
        d = dial_in_analyst.build_scan_diagnosis(cfg, report)
        ids = [c["id"] for c in d["coherence_checks"]]
        self.assertIn("hard_exit_stricter_than_min_liquidity", ids)

    def test_wallet_wall_narrative(self):
        cfg = _make_config({})
        report = {
            "scanned_count": 100,
            "candidate_count": 0,
            "candidate_count_pre_capacity": 0,
            "rejected_count": 100,
            "rejection_breakdown": {"tvl_below_threshold": 100},
            "wallet_capacity": {
                "capacity": {"max_positions": 0, "position_size_sol": 0.1, "reserved_sol": 0.02},
                "balance": {"sol": 0.0},
            },
        }
        d = dial_in_analyst.build_scan_diagnosis(cfg, report)
        blob = "\n".join(d["narrative_lines"])
        self.assertIn("max_positions=0", blob)

    def test_print_appends_to_verdict_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "v.log"
            log.write_text("start\n", encoding="utf-8")
            cfg_stream = verdicts.StreamConfig(
                enabled=False,
                color=False,
                stream=io.StringIO(),
                verdict_log_path=str(log),
            )
            diag = {
                "objective_bias_id": dial_in_analyst.OBJECTIVE_BIAS_ID,
                "bottleneck_shape": "x",
                "scan_signal": "y",
                "scan_summary": {"scanned": 1, "candidates": 0, "rejected": 1, "pass_rate_pct": 0.0},
                "narrative_lines": ["line a"],
                "setting_pressure": [],
            }
            buf = io.StringIO()
            dial_in_analyst.print_scan_diagnosis(diag, stream_cfg=cfg_stream, file=buf)
            self.assertIn("[objective-engine]", buf.getvalue())
            tail = log.read_text(encoding="utf-8")
            self.assertIn("[objective-engine]", tail)


if __name__ == "__main__":
    unittest.main()
