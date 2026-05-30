"""Pay-token-only CLMM opens: deposit and fee bias toward SOL / USDC / USDT, not the alt leg."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

WSOL_MINT = "So11111111111111111111111111111111111111112"
DEFAULT_PAY_SYMBOLS = frozenset({"SOL", "WSOL", "USDC", "USDT", "USD1"})
PAY_PREFERENCE = ("SOL", "USDC", "USDT", "USD1")


def _norm_symbol(sym: str) -> str:
    s = (sym or "").strip().upper()
    return "SOL" if s == "WSOL" else s


def allowed_pay_symbols(config: Any | None) -> frozenset[str]:
    if config is None:
        return DEFAULT_PAY_SYMBOLS
    raw = getattr(config, "allowed_quote_symbols", None)
    if not raw:
        return DEFAULT_PAY_SYMBOLS
    out = {_norm_symbol(str(x)) for x in raw if str(x).strip()}
    out.discard("")
    return frozenset(out or DEFAULT_PAY_SYMBOLS)


def pay_token_only_enabled(config: Any | None) -> bool:
    if config is None:
        return True
    return bool(getattr(config, "lp_open_pay_token_only", True))


@dataclass(frozen=True)
class PayMintResolution:
    pay_mint: str
    pay_symbol: str
    alt_mint: str
    alt_symbol: str
    pay_is_mint_a: bool


def resolve_pay_mint(pool: Mapping[str, Any], config: Any | None = None) -> PayMintResolution | None:
    """Pick the pool's pay leg (SOL/USDC/USDT/USD1). Returns None if neither side qualifies."""

    allowed = allowed_pay_symbols(config)
    prefer = _norm_symbol(
        str(
            getattr(config, "lp_pay_prefer_symbol", None)
            or getattr(config, "emergency_base_symbol", None)
            or "SOL"
        )
    )
    mint_a = str(pool.get("mint_a") or "")
    mint_b = str(pool.get("mint_b") or "")
    sym_a = _norm_symbol(str(pool.get("mint_a_symbol") or ""))
    sym_b = _norm_symbol(str(pool.get("mint_b_symbol") or ""))

    candidates: list[tuple[str, str, bool]] = []
    if sym_a in allowed and mint_a:
        candidates.append((mint_a, sym_a, True))
    if sym_b in allowed and mint_b:
        candidates.append((mint_b, sym_b, False))

    if not candidates:
        return None

    order = [prefer, *[s for s in PAY_PREFERENCE if s != prefer]]
    chosen: tuple[str, str, bool] | None = None
    for sym in order:
        for row in candidates:
            if row[1] == sym:
                chosen = row
                break
        if chosen:
            break
    if chosen is None:
        chosen = candidates[0]

    pay_mint, pay_sym, pay_is_a = chosen
    if pay_is_a:
        alt_mint, alt_sym = mint_b, sym_b
    else:
        alt_mint, alt_sym = mint_a, sym_a
    if pay_sym == "SOL" and pay_mint != WSOL_MINT and mint_a == WSOL_MINT and sym_a == "SOL":
        pay_mint = WSOL_MINT
    return PayMintResolution(
        pay_mint=pay_mint,
        pay_symbol=pay_sym,
        alt_mint=alt_mint,
        alt_symbol=alt_sym,
        pay_is_mint_a=pay_is_a,
    )


def pay_mint_open_error(pool: Mapping[str, Any], config: Any | None = None) -> str:
    syms = sorted(
        {
            _norm_symbol(str(pool.get("mint_a_symbol") or "")),
            _norm_symbol(str(pool.get("mint_b_symbol") or "")),
        }
        - {""}
    )
    allowed = ", ".join(sorted(allowed_pay_symbols(config)))
    return (
        f"Pay-token-only LP opens require a {allowed} leg; pair has {syms or 'unknown symbols'}. "
        "Skip this pool or disable lp_open_pay_token_only in settings."
    )


def apply_pay_token_only_open(
    resolution: PayMintResolution,
    open_kwargs: Mapping[str, Any],
    *,
    width_pct: float,
) -> dict[str, Any]:
    """Apply pay mint to open kwargs.

    Straddling strategies (``single_side`` is None) keep a centered band so spot
    stays in range. One-sided strategies (asymmetric / trailing skew) still map
    to single_above (mintA pay) or single_below (mintB pay).
    """

    kw = dict(open_kwargs)
    single = kw.get("single_side")
    centered = single is None or str(single).lower() in ("none", "null", "")

    kw["input_mint"] = resolution.pay_mint
    kw["pay_mint_only"] = True
    kw["pay_symbol"] = resolution.pay_symbol

    if centered:
        lower = float(kw.get("tick_lower_pct_below") or 10)
        upper = float(kw.get("tick_upper_pct_above") or 10)
        is_full = lower >= 40 and upper >= 40
        # One-sided deposit: straddle spot but sit near the pay-mint edge of the band.
        if resolution.pay_is_mint_a:
            kw["tick_lower_pct_below"] = (
                max(2.0, min(lower, 4.0)) if is_full else max(1.5, min(lower, 3.0))
            )
            kw["tick_upper_pct_above"] = upper
        else:
            kw["tick_lower_pct_below"] = lower
            kw["tick_upper_pct_above"] = (
                max(2.0, min(upper, 4.0)) if is_full else max(1.5, min(upper, 3.0))
            )
        kw["_lp_placement"] = "full_range" if is_full else "centered"
        return kw

    steps = int(kw.get("band_tick_steps") or 10)
    width = float(kw.get("single_side_width_pct") or width_pct or 15.0)
    if resolution.pay_is_mint_a:
        kw["single_side"] = "above"
        placement = "single_above"
    else:
        kw["single_side"] = "below"
        placement = "single_below"
    kw["single_side_start_pct"] = float(kw.get("single_side_start_pct") or 0.5)
    kw["single_side_width_pct"] = width
    kw["band_tick_steps"] = steps
    kw["_lp_placement"] = placement
    return kw


def enrich_open_style_for_pay(
    style_label: str,
    style_key: str,
    placement: str,
    resolution: PayMintResolution,
) -> tuple[str, str, str]:
    if placement in ("full_range", "centered"):
        label = f"{style_label} · pay {resolution.pay_symbol} only"
        key = f"{style_key}|pay_{resolution.pay_symbol}"
        return label, key, placement
    place = "single_above" if resolution.pay_is_mint_a else "single_below"
    label = f"{style_label} · pay {resolution.pay_symbol} only"
    key = f"{style_key}|pay_{resolution.pay_symbol}"
    return label, key, place
