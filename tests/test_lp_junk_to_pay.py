"""Pay-type settlement: generic pair — pay is SOL, non-pay is whatever the other symbol is."""

from __future__ import annotations

from raydium_lp1.lp_junk_to_pay import (
    fund_non_pay_leg_from_pay_mint,
    non_pay_mints_for_pool,
    non_pay_symbol_for_pool,
    resolve_pay_output_for_pool,
    settlement_policy_for_pool,
)
from raydium_lp1.lp_pay_mint import resolve_pay_mint
from raydium_lp1.routes import WSOL_MINT


def _sol_meme_pool() -> dict:
    return {
        "mint_a": WSOL_MINT,
        "mint_a_symbol": "SOL",
        "mint_b": "TokenMint11111111111111111111111111111111",
        "mint_b_symbol": "MEME",
        "price": 1000.0,
    }


class _Cfg:
    lp_pay_prefer_symbol = ""
    lp_open_pay_token_only = True
    allowed_quote_symbols = {"SOL", "USDC", "USDT"}
    lp_sweep_junk_to_pay_leg = True


def test_pay_type_is_sol_sweep_sink():
    pool = _sol_meme_pool()
    out = resolve_pay_output_for_pool(pool, _Cfg())
    assert out == (WSOL_MINT, "SOL")


def test_non_pay_mint_is_other_side_not_sol():
    pool = _sol_meme_pool()
    non_pay = non_pay_mints_for_pool(pool, _Cfg())
    assert WSOL_MINT not in non_pay
    assert "TokenMint11111111111111111111111111111111" in non_pay


def test_non_pay_symbol_from_pool_metadata():
    assert non_pay_symbol_for_pool(_sol_meme_pool(), _Cfg()) == "MEME"


def test_settlement_policy_is_symbol_agnostic():
    pol = settlement_policy_for_pool(_sol_meme_pool(), _Cfg())
    assert pol["pay_type_symbol"] == "SOL"
    assert pol["non_pay_symbol"] == "MEME"
    assert pol["fund_from_pay_type_only"] is True


def test_fund_swap_is_pay_to_non_pay(monkeypatch):
    pool = _sol_meme_pool()

    def fake_swap(**kwargs):
        assert kwargs["input_mint"] == WSOL_MINT
        assert kwargs["output_mint"] == pool["mint_b"]
        return {"ok": True, "signature": "sig"}

    monkeypatch.setattr("raydium_lp1.raydium_clmm.swap_tokens", fake_swap)
    r = fund_non_pay_leg_from_pay_mint(
        pool, target_non_pay_usd=10.0, sol_price_usd=180.0, config=_Cfg()
    )
    assert "pay(SOL)→non_pay(MEME)" == r.get("direction")
    assert r.get("non_pay_symbol") == "MEME"


def test_resolve_pay_mint_labels_non_pay():
    pay = resolve_pay_mint(_sol_meme_pool(), _Cfg())
    assert pay is not None
    assert pay.pay_symbol == "SOL"
    assert pay.alt_symbol == "MEME"
