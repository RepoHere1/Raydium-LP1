"""Harvest fee options: pay-type sink, non-pay swept only."""

from __future__ import annotations

from raydium_lp1.lp_harvest_fees import harvest_options_for_pool
from raydium_lp1.routes import USDC_MINT, WSOL_MINT


class _Cfg:
    lp_pay_prefer_symbol = ""
    lp_open_pay_token_only = True
    allowed_quote_symbols = {"SOL", "USDC", "USDT"}
    lp_sweep_junk_to_pay_leg = True


def _zinc_usdc_pool() -> dict:
    return {
        "mint_a": "ZincMint1111111111111111111111111111111",
        "mint_a_symbol": "ZINC",
        "mint_b": USDC_MINT,
        "mint_b_symbol": "USDC",
        "price": 1.0,
    }


def test_harvest_pay_type_is_usdc_for_zinc_usdc():
    opts = harvest_options_for_pool(_zinc_usdc_pool(), _Cfg())
    assert opts["pay_symbol"] == "USDC"
    assert opts["non_pay_symbol"] == "ZINC"
    assert opts["trash_output_mint"] == USDC_MINT
    assert opts["use_sol_balance"] is False
    assert opts["sweep_non_pay_to_pay_type"] is True
    assert USDC_MINT in opts["trash_keep_mints"]


def test_harvest_sol_pool_uses_native_sol_balance():
    pool = {
        "mint_a": WSOL_MINT,
        "mint_a_symbol": "SOL",
        "mint_b": "MemeMint111111111111111111111111111111",
        "mint_b_symbol": "MEME",
    }
    opts = harvest_options_for_pool(pool, _Cfg())
    assert opts["trash_output_mint"] == WSOL_MINT
    assert opts["use_sol_balance"] is True
