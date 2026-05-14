import unittest

from raydium_lp1.quote_only_entry import (
    QuoteOnlyEntryConfig,
    base_side,
    evaluate_quote_only_entry,
)


def _pool(a_sym="SOL", b_sym="MEME", a_mint="sol-mint", b_mint="meme-mint", pool_type="Concentrated"):
    return {
        "type": pool_type,
        "mint_a_symbol": a_sym,
        "mint_b_symbol": b_sym,
        "mint_a": a_mint,
        "mint_b": b_mint,
    }


class QuoteOnlyEntryTests(unittest.TestCase):
    def test_disabled_passes_everything(self):
        config = QuoteOnlyEntryConfig(enabled=False, allowed_quote_symbols=frozenset({"USDC"}))
        ok, reason = evaluate_quote_only_entry(_pool("FOO", "BAR"), config)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_passes_when_one_side_is_quote(self):
        config = QuoteOnlyEntryConfig()
        ok, reason = evaluate_quote_only_entry(_pool("SOL", "MEME"), config)
        self.assertTrue(ok, msg=reason)

    def test_rejects_when_neither_side_is_quote(self):
        config = QuoteOnlyEntryConfig()
        ok, reason = evaluate_quote_only_entry(_pool("ABC", "DEF"), config)
        self.assertFalse(ok)
        self.assertIn("quote_only_entry refuses", reason)

    def test_allow_quote_quote_pools_toggle(self):
        config_allow = QuoteOnlyEntryConfig(allow_quote_quote_pools=True)
        ok, _ = evaluate_quote_only_entry(_pool("USDC", "USDT"), config_allow)
        self.assertTrue(ok)
        config_forbid = QuoteOnlyEntryConfig(allow_quote_quote_pools=False)
        ok, reason = evaluate_quote_only_entry(_pool("USDC", "USDT"), config_forbid)
        self.assertFalse(ok)
        self.assertIn("both sides are quotes", reason)

    def test_require_concentrated_pool(self):
        config = QuoteOnlyEntryConfig(require_concentrated_pool=True)
        ok, reason = evaluate_quote_only_entry(_pool(pool_type="Standard"), config)
        self.assertFalse(ok)
        self.assertIn("not Concentrated", reason)
        ok, _ = evaluate_quote_only_entry(_pool(pool_type="Concentrated"), config)
        self.assertTrue(ok)

    def test_base_side_returns_unknown_token(self):
        config = QuoteOnlyEntryConfig()
        mint, symbol = base_side(_pool("SOL", "MEME", "sol-mint", "meme-mint"), config)
        self.assertEqual(mint, "meme-mint")
        self.assertEqual(symbol, "MEME")
        mint, symbol = base_side(_pool("MEME", "USDC", "meme-mint", "usdc-mint"), config)
        self.assertEqual(mint, "meme-mint")
        self.assertEqual(symbol, "MEME")

    def test_usd1_is_a_valid_quote_when_listed(self):
        config = QuoteOnlyEntryConfig(allowed_quote_symbols=frozenset({"SOL", "USDC", "USDT", "USD1"}))
        ok, _ = evaluate_quote_only_entry(_pool("USD1", "MEME"), config)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
