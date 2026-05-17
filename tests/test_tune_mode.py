import unittest

from raydium_lp1.scanner import ScannerConfig, effective_scan_config, raydium_pool_sort_param


class TuneModeTests(unittest.TestCase):
    def test_tune_mode_disables_slow_checks_and_sorts_liquidity(self):
        cfg = ScannerConfig(
            scan_tune_mode=True,
            pool_sort_field="",
            require_sell_route=True,
            verify_pool_on_chain=True,
            require_verified_raydium_pool=True,
            momentum_enabled=True,
        )
        out = effective_scan_config(cfg)
        self.assertFalse(out.require_sell_route)
        self.assertFalse(out.verify_pool_on_chain)
        self.assertFalse(out.require_verified_raydium_pool)
        self.assertFalse(out.momentum_enabled)
        self.assertEqual(raydium_pool_sort_param(out), "liquidity")


if __name__ == "__main__":
    unittest.main()
