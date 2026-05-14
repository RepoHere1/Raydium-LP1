import io
import sys
import unittest
from unittest.mock import patch

from raydium_lp1 import verdicts
from raydium_lp1.scanner import ScannerConfig, scan


def _pool(pid="p", apr=1500, tvl=5000, vol=1000, sym_b="MEME"):
    return {
        "id": pid,
        "apr24h": apr,
        "tvl": tvl,
        "volume24h": vol,
        "mintA": {"symbol": "SOL", "address": "solmint"},
        "mintB": {"symbol": sym_b, "address": f"mint-{pid}"},
    }


class StreamConfigTests(unittest.TestCase):
    def test_default_out_stream_is_stderr(self):
        cfg = verdicts.make_stream_config(enabled=True, max_rejections_shown=5)
        self.assertIs(cfg.out(), sys.stderr)


class StreamingTests(unittest.TestCase):
    def test_pass_emits_green_line(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(enabled=True, color=True, show_passes=True, stream=stream)
        verdicts.emit_pass(
            {"id": "p1", "mint_a_symbol": "SOL", "mint_b_symbol": "MEME",
             "apr": 1500.0, "liquidity_usd": 5000, "volume_24h_usd": 1000},
            cfg,
        )
        out = stream.getvalue()
        self.assertIn("[PASS]", out)
        self.assertIn("SOL/MEME", out)
        self.assertIn("\033[32m", out)  # green ANSI

    def test_reject_emits_red_line_with_reason(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(enabled=True, color=True, show_passes=True, stream=stream)
        verdicts.emit_reject(
            {"id": "p2", "mint_a_symbol": "SOL", "mint_b_symbol": "RUG",
             "apr": 4000.0, "liquidity_usd": 1, "volume_24h_usd": 0},
            ["liquidity $1.00 below $200.00"],
            cfg,
        )
        out = stream.getvalue()
        self.assertIn("[REJ ]", out)
        self.assertIn("SOL/RUG", out)
        self.assertIn("reason=liquidity", out)
        self.assertIn("\033[31m", out)  # red ANSI

    def test_quiet_mode_emits_nothing(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(enabled=False, color=False, stream=stream)
        verdicts.emit_pass({"id": "p3", "mint_a_symbol": "SOL", "mint_b_symbol": "X"}, cfg)
        verdicts.emit_reject({"id": "p3"}, ["x"], cfg)
        self.assertEqual(stream.getvalue(), "")

    def test_show_passes_false_hides_passes_but_shows_rejects(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(enabled=True, color=False, show_passes=False, stream=stream)
        verdicts.emit_pass({"id": "p", "mint_a_symbol": "SOL", "mint_b_symbol": "X"}, cfg)
        verdicts.emit_reject({"id": "p", "mint_a_symbol": "SOL", "mint_b_symbol": "X"}, ["liquidity ..."], cfg)
        out = stream.getvalue()
        self.assertNotIn("[PASS]", out)
        self.assertIn("[REJ ]", out)

    def test_max_rejections_caps_output(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(
            enabled=True, color=False, show_passes=False,
            max_rejections_shown=3, stream=stream,
        )
        for i in range(10):
            verdicts.emit_reject({"id": f"p{i}", "mint_a_symbol": "SOL", "mint_b_symbol": "X"}, ["liquidity x"], cfg, idx=i)
        out = stream.getvalue()
        self.assertEqual(out.count("[REJ ]"), 3)
        self.assertIn("more rejects hidden", out)


class ClassifierTests(unittest.TestCase):
    def test_classify_apr(self):
        self.assertEqual(verdicts._classify_reason("apr 12.0 below 500.00"), "apr_below_threshold")

    def test_classify_tvl(self):
        self.assertEqual(verdicts._classify_reason("liquidity $1.00 below $200.00"), "tvl_below_threshold")

    def test_classify_volume(self):
        self.assertEqual(verdicts._classify_reason("24h volume $5.00 below $50.00"), "volume_below_threshold")

    def test_classify_quote_symbol(self):
        self.assertEqual(verdicts._classify_reason("no allowed quote symbol in ['X']"), "quote_symbol_not_allowed")


class BreakdownTests(unittest.TestCase):
    def test_breakdown_groups_by_category(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(enabled=True, color=False, stream=stream)
        counts = {"tvl_below_threshold": 24700, "apr_below_threshold": 250, "volume_below_threshold": 50}
        verdicts.print_rejection_breakdown(counts, cfg)
        out = stream.getvalue()
        self.assertIn("tvl_below_threshold", out)
        self.assertIn("24,700", out)
        self.assertIn("98.8%", out)


class ScannerVerdictIntegrationTests(unittest.TestCase):
    def test_scan_emits_pass_and_reject_lines(self):
        api_response = {
            "data": {"data": [
                _pool("good", apr=1500, tvl=5000, vol=1000, sym_b="MEME"),
                _pool("bad", apr=10, tvl=1, vol=0, sym_b="RUG"),
            ]}
        }
        stream = io.StringIO()
        stream_cfg = verdicts.StreamConfig(enabled=True, color=False, stream=stream)
        config = ScannerConfig(
            min_apr=500, min_liquidity_usd=200, min_volume_24h_usd=50,
            require_sell_route=False, track_liquidity_health=False,
        )
        with patch("raydium_lp1.scanner.fetch_json", return_value=api_response):
            report = scan(config, verdict_stream=stream_cfg)
        out = stream.getvalue()
        self.assertIn("[PASS]", out)
        self.assertIn("[REJ ]", out)
        self.assertIn("SOL/MEME", out)
        self.assertIn("SOL/RUG", out)
        # Breakdown counts should appear in the report:
        self.assertIn("apr_below_threshold", report["rejection_breakdown"])


if __name__ == "__main__":
    unittest.main()
