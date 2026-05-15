import unittest

from raydium_lp1 import wallet


VALID_ADDRESS = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


class WalletConfigTests(unittest.TestCase):
    def test_load_wallet_missing_returns_none_when_not_required(self):
        self.assertIsNone(wallet.load_wallet(env={}))

    def test_load_wallet_missing_raises_when_required(self):
        with self.assertRaises(wallet.WalletError):
            wallet.load_wallet(env={}, required=True)

    def test_load_wallet_validates_address(self):
        with self.assertRaises(wallet.WalletError):
            wallet.load_wallet(env={"WALLET_ADDRESS": "not-a-real-address!"})

    def test_load_wallet_redacts_private_key(self):
        cfg = wallet.load_wallet(
            env={"WALLET_ADDRESS": VALID_ADDRESS, "WALLET_PRIVATE_KEY": "supersecretkeyvalue"}
        )
        self.assertIsNotNone(cfg)
        self.assertTrue(cfg.has_private_key())
        self.assertIn("REDACTED", cfg.redacted_key())
        self.assertNotIn("supersecretkeyvalue", repr(cfg))
        self.assertNotIn("supersecretkeyvalue", str(cfg.to_dict()))

    def test_override_wallet_returns_new_instance(self):
        cfg = wallet.override_wallet(VALID_ADDRESS)
        self.assertEqual(cfg.address, VALID_ADDRESS)
        self.assertEqual(cfg.source, "override")

    def test_override_wallet_validates_address(self):
        with self.assertRaises(wallet.WalletError):
            wallet.override_wallet("nope")

    def test_sell_all_to_base_builds_plans_and_skips_base(self):
        cfg = wallet.override_wallet(VALID_ADDRESS)
        holdings = [
            wallet.TokenHolding(mint="solmint", symbol="SOL", amount=1_000_000_000, decimals=9),
            wallet.TokenHolding(mint="rugmint", symbol="RUG", amount=500_000, decimals=6),
            wallet.TokenHolding(mint="zeromint", symbol="ZERO", amount=0, decimals=6),
        ]
        plan = wallet.sell_all_to_base(cfg, holdings, base_symbol="SOL", max_slippage_pct=0.30)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["base_symbol"], "SOL")
        self.assertEqual(len(plan["plans"]), 1)
        self.assertEqual(plan["plans"][0]["input_symbol"], "RUG")
        self.assertEqual(plan["plans"][0]["slippage_bps"], 3000)
        skipped_symbols = {item["symbol"] for item in plan["skipped"]}
        self.assertIn("SOL", skipped_symbols)
        self.assertIn("ZERO", skipped_symbols)


if __name__ == "__main__":
    unittest.main()
