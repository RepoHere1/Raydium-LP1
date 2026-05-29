"""Doctor data-flow integrity checks."""

from __future__ import annotations

import unittest

from raydium_lp1.doctor_data_flow import run_data_flow_checks, summarize_data_flow


class DoctorDataFlowTests(unittest.TestCase):
    def test_summarize_empty_ok(self) -> None:
        s = summarize_data_flow([])
        self.assertTrue(s["ok"])

    def test_run_without_files_warns(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            checks = run_data_flow_checks(
                latest_path=Path(tmp) / "missing.json",
                dashboard_path=Path(tmp) / "missing2.json",
                dashboard_port=59999,
            )
            self.assertTrue(any(c.name == "latest_json" for c in checks))


if __name__ == "__main__":
    unittest.main()
