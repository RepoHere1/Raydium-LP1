"""Pay-token-only CLMM open resolution."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from raydium_lp1.lp_open_style import resolve_live_open_style
from raydium_lp1.lp_order_strategies import STRATEGY_CENTERED_TIGHT, STRATEGY_FULL_RANGE
from raydium_lp1.lp_pay_mint import (
    apply_pay_token_only_open,
    pay_mint_open_error,
    resolve_pay_mint,
)


class LpPayMintTests(unittest.TestCase):
    def test_resolve_sol_on_mint_a(self) -> None:
        pool = {
            "mint_a": "So11111111111111111111111111111111111111112",
            "mint_b": "AltMint",
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "DEGEN",
        }
        res = resolve_pay_mint(pool, SimpleNamespace(allowed_quote_symbols={"SOL", "USDC"}))
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res.pay_is_mint_a)
        self.assertEqual(res.pay_symbol, "SOL")

    def test_resolve_usdc_on_mint_b(self) -> None:
        pool = {
            "mint_a": "AltMint",
            "mint_b": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "mint_a_symbol": "DEGEN",
            "mint_b_symbol": "USDC",
        }
        res = resolve_pay_mint(pool)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertFalse(res.pay_is_mint_a)
        self.assertEqual(res.pay_symbol, "USDC")

    def test_no_pay_leg_returns_none(self) -> None:
        pool = {"mint_a_symbol": "FOO", "mint_b_symbol": "BAR", "mint_a": "a", "mint_b": "b"}
        self.assertIsNone(resolve_pay_mint(pool))

    def test_apply_forces_single_below_for_usdc_b(self) -> None:
        pool = {
            "mint_a": "Alt",
            "mint_b": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "mint_a_symbol": "MEME",
            "mint_b_symbol": "USDC",
        }
        res = resolve_pay_mint(pool)
        assert res is not None
        kw = apply_pay_token_only_open(
            res,
            {"single_side": None, "tick_lower_pct_below": 10, "tick_upper_pct_above": 10},
            width_pct=20.0,
        )
        self.assertEqual(kw["single_side"], "below")
        self.assertEqual(kw["input_mint"], res.pay_mint)
        self.assertTrue(kw["pay_mint_only"])

    def test_centered_strategy_becomes_pay_only(self) -> None:
        pool = {
            "mint_a": "So11111111111111111111111111111111111111112",
            "mint_b": "Alt",
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "DEGEN",
        }
        cfg = SimpleNamespace(
            lp_active_strategy=STRATEGY_CENTERED_TIGHT,
            lp_default_range_width_pct=12.0,
            lp_skew_use_momentum=False,
            lp_open_pay_token_only=True,
            allowed_quote_symbols={"SOL", "USDC", "USDT"},
        )
        style = resolve_live_open_style(cfg, pool)
        self.assertEqual(style.placement, "single_above")
        self.assertEqual(style.open_kwargs.get("single_side"), "above")
        self.assertTrue(style.open_kwargs.get("pay_mint_only"))
        self.assertIn("pay SOL only", style.lp_style_label)

    def test_full_range_overridden_to_pay_side(self) -> None:
        pool = {
            "mint_a": "So11111111111111111111111111111111111111112",
            "mint_b": "Alt",
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "DEGEN",
        }
        cfg = SimpleNamespace(
            lp_active_strategy=STRATEGY_FULL_RANGE,
            lp_default_range_width_pct=40.0,
            lp_skew_use_momentum=False,
            lp_open_pay_token_only=True,
            allowed_quote_symbols={"SOL", "USDC", "USDT"},
        )
        style = resolve_live_open_style(cfg, pool)
        self.assertIn(style.open_kwargs.get("single_side"), ("above", "below"))
        self.assertIsNotNone(style.open_kwargs.get("input_mint"))

    def test_pay_error_message(self) -> None:
        err = pay_mint_open_error({"mint_a_symbol": "A", "mint_b_symbol": "B"})
        self.assertIn("Pay-token-only", err)


if __name__ == "__main__":
    unittest.main()
