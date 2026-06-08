"""Permanent LP1 policy: never pay non-recoverable CLMM escrow (tick-array rent).

Raydium CLMM terminology used in LP1
-------------------------------------
- **Recoverable rent** (~0.007–0.009 SOL): position NFT + personal position state.
  Locked briefly in the wallet; returned on close/burn. Required for every open — allowed.
- **Escrow / sunk tick-array rent** (~0.072 SOL per *new* tick-array account): non-recoverable
  SOL spent when the SDK must *create* tick-array accounts for a band the pool lacks.
  Also called **new-band rent** or **tick-array initialization cost**. **Never allowed.**
- **Literal pool full range** (min/max ticks): forces many new tick arrays (~0.15 SOL sunk).
  Always blocked.
- **Wide band** (≤80% centered): usually reuses existing tick arrays on active pools;
  blocked only when the rent model estimates material sunk cost.

This module is **hardwired** for every order type and LIVE path. Settings cannot disable it.
"""

from __future__ import annotations

from typing import Any, Mapping

from raydium_lp1.fee_guard import FeeGuardBlockedError

POLICY_ID = "no_escrow_paid_permanent"
POLICY_VERSION = 1
SUNK_RENT_EPSILON_SOL = 1e-6

# Settings keys forced on every open (user overrides are ignored).
FORCED_SETTINGS: dict[str, Any] = {
    "no_escrow_paid_policy": POLICY_ID,
    "lp_rent_conservative_estimates": False,
    "spend_less_auto_fallback_from_wide": False,
}


def policy_manifest() -> dict[str, Any]:
    return {
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "sunk_rent_tolerance_sol": SUNK_RENT_EPSILON_SOL,
        "forced_settings": dict(FORCED_SETTINGS),
        "blocks": [
            "literal_pool_full_range",
            "any_estimated_sunk_tick_array_rent",
            "lp_rent_conservative_estimates (ignored — always false)",
            "spend_less_auto_fallback_from_wide (ignored — always false)",
        ],
        "allows": [
            "recoverable_position_nft_rent (~0.008 SOL, returned on close)",
            "network_fees (base + priority)",
            "optional_spl_ata_create (~0.002 SOL, recoverable if closed)",
        ],
    }


def normalize_settings_no_escrow(settings: Any | None) -> dict[str, Any]:
    """Return settings with permanent NO ESCROW overrides applied."""

    if isinstance(settings, dict):
        out = dict(settings)
    elif settings is None:
        out = {}
    else:
        out = dict(getattr(settings, "__dict__", {}) or {})
    for key, value in FORCED_SETTINGS.items():
        out[key] = value
    return out


def _band_width_pct(open_kwargs: Mapping[str, Any] | None) -> float:
    from raydium_lp1.lp_full_range import DEFAULT_WIDE_BAND_WIDTH_PCT, MAX_WIDE_BAND_WIDTH_PCT, is_wide_band_open_kwargs

    if not open_kwargs:
        return 20.0
    if is_wide_band_open_kwargs(open_kwargs) or open_kwargs.get("wide_range"):
        return float(open_kwargs.get("wide_range_width_pct") or DEFAULT_WIDE_BAND_WIDTH_PCT)
    w = open_kwargs.get("single_side_width_pct")
    if w is not None:
        return float(w)
    lo = float(open_kwargs.get("tick_lower_pct_below") or 10)
    hi = float(open_kwargs.get("tick_upper_pct_above") or 10)
    return min(MAX_WIDE_BAND_WIDTH_PCT, lo + hi)


def open_kwargs_violation(open_kwargs: Mapping[str, Any] | None) -> str | None:
    """Return a human reason if open kwargs are forbidden under NO ESCROW policy."""

    kw = dict(open_kwargs or {})
    if kw.get("literal_pool_full_range"):
        return (
            "Literal pool min/max full range would initialize many tick-array accounts "
            "(~0.15 SOL sunk escrow). Use standard wide band (max 80%) instead."
        )
    if kw.get("wallet_inventory_full_range") and kw.get("literal_pool_full_range"):
        return "Wallet inventory literal full range is disabled under NO ESCROW PAID policy."
    return None


def assert_no_escrow_paid(
    *,
    deposit_sol: float,
    open_kwargs: Mapping[str, Any] | None = None,
    settings: Any | None = None,
    priority_micro: int | None = None,
    pay_needs_ata: bool = False,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    """Raise FeeGuardBlockedError if this open would pay sunk tick-array escrow.

    Returns a dict with policy manifest + rent escrow estimate when allowed.
    """

    from raydium_lp1.lp_rent_escrow import estimate_open_rent_escrow

    normalized = normalize_settings_no_escrow(settings)
    kw_violation = open_kwargs_violation(open_kwargs)
    if kw_violation:
        raise FeeGuardBlockedError(f"NO ESCROW PAID: {kw_violation}")

    est = estimate_open_rent_escrow(
        deposit_sol=deposit_sol,
        open_kwargs=open_kwargs,
        settings=normalized,
        priority_micro=priority_micro,
        pay_needs_ata=pay_needs_ata,
    )

    if est.new_tick_arrays_est > 0 or est.sunk_sol_est > SUNK_RENT_EPSILON_SOL:
        width = _band_width_pct(open_kwargs)
        raise FeeGuardBlockedError(
            "NO ESCROW PAID: this band shape may require new tick-array accounts "
            f"(sunk ~{est.sunk_sol_est:.4f} SOL, {est.new_tick_arrays_est} array(s) est.). "
            f"Placement={est.placement}, band~{width:.0f}% wide. "
            "Pick a busier pool, narrow the band, or use a placement that reuses existing arrays. "
            "Recoverable position NFT rent (~0.008 SOL) is still required and returned on close."
        )

    if est.literal_pool_ticks:
        raise FeeGuardBlockedError(
            "NO ESCROW PAID: literal pool ticks are disabled for all order types."
        )

    return {
        "no_escrow_policy": policy_manifest(),
        "rent_escrow": est.to_dict(),
        "strategy_id": strategy_id,
        "deposit_sol": round(float(deposit_sol), 6),
    }
