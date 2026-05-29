"""LP order rules (abandoned pools, close defaults)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from raydium_lp1.lp_order_rules import (
    ABANDONED_POOL_IDS,
    close_sweep_trash_enabled,
    close_trash_swap_attempts,
    pool_open_blocked,
)


class LpOrderRulesTests(unittest.TestCase):
    def test_tslax_pool_abandoned(self) -> None:
        pid = "HHQUnUbmWLrYzkscDY1C3deEFbGtiGBGoHjpANogmvum"
        self.assertIn(pid, ABANDONED_POOL_IDS)
        msg = pool_open_blocked(pid)
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("abandoned", msg.lower())

    def test_settings_blocked_pool_ids(self) -> None:
        cfg = SimpleNamespace(blocked_pool_ids={"PoolXYZ123"})
        self.assertIn("PoolXYZ123", pool_open_blocked("PoolXYZ123", cfg) or "")

    def test_close_sweep_defaults(self) -> None:
        self.assertTrue(close_sweep_trash_enabled(None))
        self.assertEqual(close_trash_swap_attempts(None), 2)


if __name__ == "__main__":
    unittest.main()
