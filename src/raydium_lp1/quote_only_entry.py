"""QuoteOnlyEntry: when (later) opening an LP, only ever deposit your safe quote assets.

The name to remember is **quote_only_entry**.

Plain English: a Raydium pool has two sides, e.g. SOL <-> RANDOMCOIN. The
"quote" side is the asset you trust (SOL, USDC, USDT, USD1). The "base" side
is the unknown token whose APR drew us in.

This policy says:
- Never swap your safe quote asset into the unknown token at entry.
- Only deposit the quote side (a "single-sided" or "one-sided" LP entry).
- If price drifts down through your range, you may *end up* holding some of
  the base token as a side effect of how AMM/CLMM LPs work, but you never
  *buy* it at entry.

For a candidate pool to even qualify:
- Exactly one of (mint_a_symbol, mint_b_symbol) must be in
  `allowed_quote_symbols`.
- If `require_concentrated_pool` is on, the pool must be a Concentrated /
  CLMM pool, because Raydium AMM v4 pools cannot accept truly one-sided
  deposits.

This module is a *gating filter* for the scanner. The actual deposit code is
intentionally not in this repo (see the project safety model in README.md).

Settings live under `quote_only_entry` in `config/settings.json`.
See SETTINGS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_QUOTE_SYMBOLS: tuple[str, ...] = ("SOL", "WSOL", "USDC", "USDT", "USD1")


@dataclass(frozen=True)
class QuoteOnlyEntryConfig:
    enabled: bool = True
    allowed_quote_symbols: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_QUOTE_SYMBOLS)
    )
    require_concentrated_pool: bool = False
    allow_quote_quote_pools: bool = True

    @classmethod
    def from_raw(cls, raw: Any) -> "QuoteOnlyEntryConfig":
        if not isinstance(raw, dict):
            return cls()
        symbols_raw = raw.get("allowed_quote_symbols", DEFAULT_QUOTE_SYMBOLS)
        symbols = frozenset(str(s).upper() for s in symbols_raw if str(s).strip())
        if "SOL" in symbols:
            symbols = symbols | {"WSOL"}
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            allowed_quote_symbols=symbols,
            require_concentrated_pool=bool(
                raw.get("require_concentrated_pool", cls.require_concentrated_pool)
            ),
            allow_quote_quote_pools=bool(raw.get("allow_quote_quote_pools", cls.allow_quote_quote_pools)),
        )


def is_concentrated_pool(pool_type: str) -> bool:
    name = (pool_type or "").lower()
    return "concentrated" in name or "clmm" in name


def base_side(
    pool: dict[str, Any],
    config: QuoteOnlyEntryConfig,
) -> tuple[str, str] | None:
    """Return (base_mint_address, base_symbol) for a quote/base pair, else None.

    If both tokens are quote assets (e.g. SOL/USDC), there is no "base" so we
    return None to signal a quote/quote pool. Callers decide whether to allow
    that via `allow_quote_quote_pools`.
    """

    a_sym = (pool.get("mint_a_symbol") or "").upper()
    b_sym = (pool.get("mint_b_symbol") or "").upper()
    a_is_quote = a_sym in config.allowed_quote_symbols
    b_is_quote = b_sym in config.allowed_quote_symbols
    if a_is_quote and not b_is_quote:
        return (pool.get("mint_b") or "", b_sym)
    if b_is_quote and not a_is_quote:
        return (pool.get("mint_a") or "", a_sym)
    return None


def evaluate_quote_only_entry(
    pool: dict[str, Any],
    config: QuoteOnlyEntryConfig,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails)."""

    if not config.enabled:
        return True, None

    a_sym = (pool.get("mint_a_symbol") or "").upper()
    b_sym = (pool.get("mint_b_symbol") or "").upper()
    a_is_quote = a_sym in config.allowed_quote_symbols
    b_is_quote = b_sym in config.allowed_quote_symbols

    if not (a_is_quote or b_is_quote):
        return False, (
            f"neither side is an allowed quote ({a_sym or '?'}/{b_sym or '?'}); "
            f"quote_only_entry refuses to buy unknown tokens"
        )

    if a_is_quote and b_is_quote and not config.allow_quote_quote_pools:
        return False, "both sides are quotes; quote_only_entry.allow_quote_quote_pools is off"

    if config.require_concentrated_pool and not is_concentrated_pool(pool.get("type", "")):
        return False, (
            f"pool type '{pool.get('type', '?')}' is not Concentrated/CLMM; "
            "true one-sided deposits require a CLMM pool"
        )

    return True, None
