import unittest

from raydium_lp1.lp_lock_guard import (
    LpLockGuardConfig,
    LpLockInspection,
    evaluate_lp_lock_guard,
)


class LpLockGuardTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        ok, _ = evaluate_lp_lock_guard(
            {"type": "Standard"}, None, LpLockGuardConfig(enabled=False),
            has_rpc_configured=False,
        )
        self.assertTrue(ok)

    def test_concentrated_pool_skipped_by_default(self):
        ok, _ = evaluate_lp_lock_guard(
            {"type": "Concentrated"},
            None,
            LpLockGuardConfig(enabled=True),
            has_rpc_configured=False,
        )
        self.assertTrue(ok)

    def test_concentrated_pool_enforced_when_flag_set(self):
        ok, reason = evaluate_lp_lock_guard(
            {"type": "Concentrated"},
            None,
            LpLockGuardConfig(enabled=True, apply_to_concentrated_pools=True),
            has_rpc_configured=False,
        )
        self.assertFalse(ok)
        self.assertIn("no Solana RPC", reason)

    def test_high_burn_passes(self):
        inspection = LpLockInspection(lp_mint="LP", burned_pct=95.0, source="rpc_incinerator_balance")
        ok, _ = evaluate_lp_lock_guard(
            {"type": "Standard"},
            inspection,
            LpLockGuardConfig(enabled=True, min_locked_or_burned_pct=90.0),
            has_rpc_configured=True,
        )
        self.assertTrue(ok)

    def test_low_burn_rejected(self):
        inspection = LpLockInspection(lp_mint="LP", burned_pct=10.0, source="rpc_incinerator_balance")
        ok, reason = evaluate_lp_lock_guard(
            {"type": "Standard"},
            inspection,
            LpLockGuardConfig(enabled=True, min_locked_or_burned_pct=90.0),
            has_rpc_configured=True,
        )
        self.assertFalse(ok)
        self.assertIn("LP burn/lock", reason)

    def test_no_inspection_no_rpc_fails_closed(self):
        ok, reason = evaluate_lp_lock_guard(
            {"type": "Standard"},
            None,
            LpLockGuardConfig(enabled=True),
            has_rpc_configured=False,
        )
        self.assertFalse(ok)
        self.assertIn("no Solana RPC", reason)

    def test_no_inspection_with_rpc_fails_closed(self):
        ok, reason = evaluate_lp_lock_guard(
            {"type": "Standard"},
            None,
            LpLockGuardConfig(enabled=True),
            has_rpc_configured=True,
        )
        self.assertFalse(ok)
        self.assertIn("could not read", reason)

    def test_no_inspection_fail_open(self):
        ok, _ = evaluate_lp_lock_guard(
            {"type": "Standard"},
            None,
            LpLockGuardConfig(enabled=True, fail_open_when_no_rpc=True),
            has_rpc_configured=False,
        )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
