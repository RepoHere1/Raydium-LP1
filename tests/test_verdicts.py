import io
import sys
import unittest
from unittest.mock import patch

from raydium_lp1 import verdicts
from raydium_lp1.scanner import ScannerConfig, scan
from tests.scan_test_defaults import RAYDIUM_CPMM_PROGRAM, SCAN_TEST_DISABLE_VERIFY


def _pool(pid="p", apr=1500, tvl=5000, vol=1000, sym_b="MEME"):
    return {
        "id": pid,
        "programId": RAYDIUM_CPMM_PROGRAM,
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
        self.assertIn("[REJ]", out)
        self.assertIn("SOL/RUG", out)
        self.assertIn("liquidity $1.00 below $200.00", out)
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
        self.assertIn("[REJ]", out)

    def test_max_rejections_caps_output(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(
            enabled=True, color=False, show_passes=False,
            max_rejections_shown=3, stream=stream,
        )
        for i in range(10):
            verdicts.emit_reject({"id": f"p{i}", "mint_a_symbol": "SOL", "mint_b_symbol": "X"}, ["liquidity x"], cfg, idx=i)
        out = stream.getvalue()
        self.assertEqual(out.count("[REJ]"), 3)
        self.assertIn("more rejects hidden", out)


class HeaderTests(unittest.TestCase):
    def test_column_headers_list_named_columns(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(enabled=True, color=False, stream=stream)
        verdicts.print_verdict_column_headers(cfg, page=3)
        out = stream.getvalue()
        self.assertIn("PAIR_NAME", out)
        self.assertIn("POOL_STATE", out)
        self.assertIn("REJECT_REASON", out)
        self.assertIn("Raydium page 3", out)

    def test_reminder_header_matches_page_header_row(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(
            enabled=True, color=False, stream=stream, pool_id_width=56, header_repeat_rows=99
        )
        verdicts.print_verdict_column_headers(cfg, page=1)
        full = stream.getvalue()
        stream.seek(0)
        stream.truncate(0)
        verdicts.print_verdict_column_reminder(cfg)
        reminder = stream.getvalue()
        hdr_lines_full = [ln for ln in full.splitlines() if ln.startswith("VERDICT")]
        hdr_lines_rem = [ln for ln in reminder.splitlines() if ln.startswith("VERDICT")]
        self.assertEqual(len(hdr_lines_full), 1)
        self.assertEqual(len(hdr_lines_rem), 1)
        self.assertEqual(hdr_lines_full[0], hdr_lines_rem[0])


class HeaderRepeatTests(unittest.TestCase):
    def test_repeat_injected_every_n_rows(self):
        stream = io.StringIO()
        cfg = verdicts.StreamConfig(enabled=True, color=False, stream=stream, header_repeat_rows=2)
        for i in range(4):
            verdicts.emit_pass(
                {
                    "id": str(i),
                    "mint_a_symbol": "S",
                    "mint_b_symbol": "T",
                    "apr": 1.0,
                    "liquidity_usd": 1.0,
                    "volume_24h_usd": 1.0,
                },
                cfg,
            )
        self.assertGreaterEqual(stream.getvalue().count("[repeat header every"), 2)


class AnsiTests(unittest.TestCase):
    def test_strip_ansi(self):
        raw = f"{verdicts._RED}hello{verdicts._RESET}"
        self.assertEqual(verdicts.strip_ansi(raw), "hello")


class VerdictLogTests(unittest.TestCase):
    def test_verdict_log_plain_text_no_escapes(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.log"
            stream = io.StringIO()
            cfg = verdicts.StreamConfig(
                enabled=True,
                color=False,
                stream=stream,
                verdict_log_path=str(path),
            )
            verdicts.emit_pass(
                {
                    "id": "PoolIdPlain123",
                    "mint_a_symbol": "S",
                    "mint_b_symbol": "T",
                    "apr": 9.0,
                    "liquidity_usd": 1.0,
                    "volume_24h_usd": 2.0,
                },
                cfg,
            )
            logged = path.read_text(encoding="utf-8")
            self.assertIn("PoolIdPlain123", logged)
            self.assertNotIn("\x1b[", logged)

    def test_log_between_scan_cycles_appends_marker(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.log"
            path.write_text("seed\n", encoding="utf-8")
            cfg = verdicts.StreamConfig(
                enabled=False,
                color=False,
                stream=io.StringIO(),
                verdict_log_path=str(path),
            )
            verdicts.log_between_scan_cycles(cfg, iso_timestamp="2026-05-14T12:00:00+00:00")
            text = path.read_text(encoding="utf-8")
            self.assertIn("seed", text)
            self.assertIn("Next scan cycle", text)
            self.assertIn("2026-05-14T12:00:00+00:00", text)


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
            **SCAN_TEST_DISABLE_VERIFY,
        )
        with patch("raydium_lp1.scanner.fetch_json", return_value=api_response):
            report = scan(config, verdict_stream=stream_cfg)
        out = stream.getvalue()
        self.assertIn("[PASS]", out)
        self.assertIn("[REJ]", out)
        self.assertIn("SOL/MEME", out)
        self.assertIn("SOL/RUG", out)
        self.assertIn("PAIR_NAME", out)
        self.assertIn("good", out)
        self.assertIn("bad", out)
        self.assertIn("apr_below_threshold", report["rejection_breakdown"])


if __name__ == "__main__":
    unittest.main()
