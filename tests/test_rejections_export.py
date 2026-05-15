import csv
import json
import tempfile
import unittest
from pathlib import Path

from raydium_lp1.scanner import write_rejections_csv


class RejectionsExportTests(unittest.TestCase):
    def test_csv_and_summary_written(self):
        rejected = [
            {
                "id": "pool-1",
                "mint_a_symbol": "SOL",
                "mint_b_symbol": "MEME",
                "mint_a": "So11111111111111111111111111111111111111112",
                "mint_b": "MemeMint1111111111111111111111111111111111",
                "apr": 1500.0,
                "liquidity_usd": 10.0,
                "volume_24h_usd": 100.0,
                "burn_percent": 100.0,
                "reasons": ["liquidity $10.00 below $200.00"],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rejections.csv"
            out = write_rejections_csv(
                rejected,
                scanned_at="2026-01-01T00:00:00+00:00",
                path=path,
                reason_histogram={"liquidity $10.00 below $200.00": 1},
                breakdown={"tvl_below_threshold": 1},
            )
            self.assertTrue(path.exists())
            with path.open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["mint_a"], "So11111111111111111111111111111111111111112")
            self.assertEqual(rows[0]["mint_b"], "MemeMint1111111111111111111111111111111111")
            self.assertEqual(rows[0].get("lp_mint_address", ""), "")
            self.assertEqual(rows[0].get("config_account_id", ""), "")
            summ = path.with_name(path.stem + ".summary.json")
            self.assertTrue(summ.exists())
            data = json.loads(summ.read_text(encoding="utf-8"))
            self.assertEqual(data["rejected_count"], 1)
            self.assertEqual(out, str(path.resolve()))


if __name__ == "__main__":
    unittest.main()
