"""Fee guard blocks micro CLMM deposits and caps priority fees."""

from __future__ import annotations

import unittest

from raydium_lp1.fee_guard import (
    FeeGuardBlockedError,
    assert_clmm_open_allowed,
    cap_priority_micro,
    estimate_clmm_open_cost_sol,
    fee_config_from_settings,
    sanitize_clmm_payload,
)


class FeeGuardTests(unittest.TestCase):
    def test_caps_priority_fee(self) -> None:
        cfg = fee_config_from_settings({"max_priority_fee_micro_lamports": 2000})
        self.assertEqual(cap_priority_micro(50_000, cfg), 2000)
        self.assertEqual(cap_priority_micro(None, cfg), 2000)

    def test_blocks_micro_deposit(self) -> None:
        cfg = fee_config_from_settings(
            {
                "fee_guard_enabled": True,
                "min_clmm_deposit_sol": 0.008,
                "block_deposits_below_sol": 0.006,
            }
        )
        with self.assertRaises(FeeGuardBlockedError):
            assert_clmm_open_allowed(0.0014, settings=cfg)

    def test_allows_sane_deposit(self) -> None:
        cfg = fee_config_from_settings(
            {
                "fee_guard_enabled": True,
                "min_clmm_deposit_sol": 0.008,
                "clmm_open_rent_sol": 0.042,
                "max_fee_pct_of_deposit": 90.0,
            }
        )
        est = assert_clmm_open_allowed(0.20, settings=cfg)
        self.assertGreater(float(est["estimated_total_sol"]), 0.04)

    def test_sanitize_payload_open(self) -> None:
        out = sanitize_clmm_payload(
            "open_position.mjs",
            {
                "pool_id": "x",
                "input_amount_human": 0.20,
                "priority_fee_micro_lamports": 99_999,
            },
            settings={
                "fee_guard_enabled": True,
                "min_clmm_deposit_sol": 0.008,
                "max_fee_pct_of_deposit": 80,
                "clmm_open_rent_sol": 0.042,
            },
        )
        self.assertLessEqual(out["priority_fee_micro_lamports"], 2000)
        self.assertIn("compute_units", out)


if __name__ == "__main__":
    unittest.main()
