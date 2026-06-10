"""Permanent NO ESCROW PAID policy — all order types."""

from __future__ import annotations

import unittest

from raydium_lp1.fee_guard import FeeGuardBlockedError, assert_clmm_open_allowed, fee_config_from_settings
from raydium_lp1.lp_full_range import open_kwargs_for_wide_band
from raydium_lp1.lp_rent_escrow import assert_rent_escrow_allowed, estimate_open_rent_escrow
from raydium_lp1.no_escrow_policy import (
    POLICY_ID,
    assert_no_escrow_paid,
    normalize_settings_no_escrow,
    policy_manifest,
)
from raydium_lp1.spend_less_get_more import SpendLessConfig, analyze_open_plan


class NoEscrowPolicyTests(unittest.TestCase):
    def test_policy_manifest(self) -> None:
        m = policy_manifest()
        self.assertEqual(m["policy_id"], POLICY_ID)
        self.assertIn("literal_pool_full_range", m["blocks"][0])

    def test_normalize_overrides_conservative_and_fallback(self) -> None:
        raw = {
            "lp_rent_conservative_estimates": True,
            "spend_less_auto_fallback_from_wide": True,
        }
        out = normalize_settings_no_escrow(raw)
        self.assertFalse(out["lp_rent_conservative_estimates"])
        self.assertFalse(out["spend_less_auto_fallback_from_wide"])
        self.assertEqual(out["no_escrow_paid_policy"], POLICY_ID)

    def test_conservative_setting_ignored_in_rent_model(self) -> None:
        dep = 3.0 / 180.0
        est = estimate_open_rent_escrow(
            deposit_sol=dep,
            open_kwargs=open_kwargs_for_wide_band(width_pct=80),
            settings={"lp_rent_conservative_estimates": True, "sol_price_usd": 180},
        )
        self.assertEqual(est.rent_model, "raydium")
        self.assertLess(est.sunk_sol_est, 0.01)

    def test_literal_pool_blocked(self) -> None:
        with self.assertRaises(FeeGuardBlockedError) as ctx:
            assert_no_escrow_paid(
                deposit_sol=1.0 / 180,
                open_kwargs={"literal_pool_full_range": True, "full_range": True},
            )
        self.assertIn("NO ESCROW PAID", str(ctx.exception))

    def test_wide_band_allowed_raydium_model(self) -> None:
        dep = 0.5 / 180
        kw = open_kwargs_for_wide_band()
        assert_no_escrow_paid(deposit_sol=dep, open_kwargs=kw)
        assert_rent_escrow_allowed(deposit_sol=dep, open_kwargs=kw)

    def test_fee_guard_wires_policy(self) -> None:
        dep = 3.0 / 180
        est = assert_clmm_open_allowed(
            dep,
            settings={
                "sol_price_usd": 180,
                "block_deposits_below_sol": 0.001,
                "min_lp_deposit_usd": 0.25,
            },
            open_kwargs=open_kwargs_for_wide_band(),
        )
        self.assertIn("no_escrow_policy", est)
        self.assertEqual(est["no_escrow_policy"]["policy_id"], POLICY_ID)

    def test_fee_config_normalizes_settings(self) -> None:
        cfg = fee_config_from_settings({"lp_rent_conservative_estimates": True})
        self.assertIsNotNone(cfg.enabled)

    def test_spend_less_disables_wide_fallback(self) -> None:
        sl = SpendLessConfig.from_settings({"spend_less_auto_fallback_from_wide": True})
        self.assertFalse(sl.auto_fallback_from_wide)

    def test_spend_less_blocks_literal_in_plan(self) -> None:
        plan = analyze_open_plan(
            requested_deposit_usd=3.0,
            open_kwargs={"literal_pool_full_range": True, "full_range": True},
            pay_symbol="SOL",
            balance_sol=1.0,
            reserve_sol=0.02,
            settings={"sol_price_usd": 180},
        )
        self.assertFalse(plan.ok)
        self.assertTrue(any("NO ESCROW PAID" in b for b in plan.block_reasons))


if __name__ == "__main__":
    unittest.main()
