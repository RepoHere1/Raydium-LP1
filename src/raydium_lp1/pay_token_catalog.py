"""Canonical pay-token mints/decimals for LP funding and route checks."""

from __future__ import annotations

from dataclasses import dataclass

from raydium_lp1.routes import USDC_MINT, USDT_MINT, WSOL_MINT

USD1_MINT = "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"

STABLE_PAY_SYMBOLS = frozenset({"USDC", "USDT", "USD1"})


@dataclass(frozen=True)
class PayTokenSpec:
    symbol: str
    mint: str
    decimals: int
    balance_field: str


PAY_TOKEN_SPECS: dict[str, PayTokenSpec] = {
    "SOL": PayTokenSpec("SOL", WSOL_MINT, 9, "sol_balance"),
    "WSOL": PayTokenSpec("WSOL", WSOL_MINT, 9, "sol_balance"),
    "USDC": PayTokenSpec("USDC", USDC_MINT, 6, "usdc_balance"),
    "USDT": PayTokenSpec("USDT", USDT_MINT, 6, "usdt_balance"),
    "USD1": PayTokenSpec("USD1", USD1_MINT, 6, "usd1_balance"),
}


def pay_token_spec(symbol: str) -> PayTokenSpec | None:
    s = (symbol or "").strip().upper()
    if s == "WSOL":
        s = "SOL"
    return PAY_TOKEN_SPECS.get(s)


def is_stable_pay_symbol(symbol: str) -> bool:
    return (symbol or "").strip().upper() in STABLE_PAY_SYMBOLS
