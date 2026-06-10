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
                "min_lp_deposit_usd": 0,
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

    def test_blocks_sub_min_usd_deposit(self) -> None:
        cfg = fee_config_from_settings(
            {
                "fee_guard_enabled": True,
                "min_lp_deposit_usd": 0.25,
                "sol_price_usd": 180.0,
                "min_clmm_deposit_sol": 0.0005,
            }
        )
        with self.assertRaises(FeeGuardBlockedError):
            assert_clmm_open_allowed(0.001, settings=cfg)  # ~$0.18

    def test_note_broadcast_skips_failed_tx(self) -> None:
        from raydium_lp1.fee_guard import _load_ledger, note_broadcast_result, reset_session_ledger

        reset_session_ledger()
        note_broadcast_result(
            "open_position.mjs",
            {"ok": False, "signature": "abc", "confirm_error": "reverted"},
            {"estimated_total_sol": 0.042},
        )
        self.assertEqual(len(_load_ledger().get("attempts") or []), 0)
        note_broadcast_result(
            "open_position.mjs",
            {"ok": True, "signature": "abc", "confirmed": True},
            {"estimated_total_sol": 0.042, "network_fee_sol": 0.00002},
        )
        led = _load_ledger()
        self.assertEqual(len(led.get("attempts") or []), 1)
        self.assertAlmostEqual(float(led.get("spent_sol_est") or 0), 0.00002, places=6)

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

    def test_usdc_pay_one_dollar_not_blocked_by_sol_floor(self) -> None:
        cfg = fee_config_from_settings(
            {
                "fee_guard_enabled": True,
                "block_deposits_below_sol": 0.006,
                "min_lp_deposit_usd": 0.25,
                "sol_price_usd": 180.0,
                "min_clmm_deposit_sol": 0.008,
                "clmm_open_rent_sol": 0.009,
                "max_fee_pct_of_deposit": 90.0,
            }
        )
        dep_sol_equiv = 1.0 / 180.0
        est = assert_clmm_open_allowed(dep_sol_equiv, settings=cfg)
        self.assertGreater(float(est["estimated_total_sol"]), 0)

    def test_sanitize_usdc_jupiter_swap_not_blocked(self) -> None:
        usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        out = sanitize_clmm_payload(
            "swap_sol_to_pay.mjs",
            {
                "input_mint": usdc,
                "output_mint": "FRE3HQDTWuhLAvWKapwLMzbw3ZSMdh76CXQqBw2bEJeV",
                "amount_raw": "378000",
            },
            settings={"fee_guard_enabled": True, "block_deposits_below_sol": 0.006},
        )
        self.assertEqual(out["input_mint"], usdc)


if __name__ == "__main__":
    unittest.main()
