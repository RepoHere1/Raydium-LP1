"""Estimate CLMM open rent / escrow before spending — block uneconomic opens.

Raydium CLMM opens lock SOL in on-chain accounts. **Recoverable** rent (NFT +
position) usually returns on close. **Sunk** rent (often edge tick-array accounts on
literal or very wide ranges) may never return. This module scores opens *before*
broadcast so deposits are not dwarfed by escrow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from raydium_lp1.fee_guard import FeeGuardBlockedError, FeeGuardConfig, fee_config_from_settings
from raydium_lp1.lp_full_range import (
    DEFAULT_WIDE_BAND_WIDTH_PCT,
    MAX_WIDE_BAND_WIDTH_PCT,
    is_wide_band_open_kwargs,
)

# Mainnet-shaped constants (SOL) from observed txs
_RECOVERABLE_BASE_SOL = 0.0055
_TICK_ARRAY_SUNK_SOL = 0.072
_NFT_ATA_EXTRA_SOL = 0.002
_PRIORITY_BUFFER_SOL = 0.00002


@dataclass(frozen=True)
class RentEscrowEstimate:
    """Pre-trade rent / escrow outlook for one CLMM open."""

    placement: str
    wide_range: bool
    literal_pool_ticks: bool
    recoverable_sol_est: float
    sunk_sol_est: float
    rent_escrow_sol: float
    priority_and_base_sol: float
    total_wallet_sol_est: float
    deposit_sol: float
    deposit_usd: float
    sol_price_usd: float
    rent_escrow_usd: float
    sunk_usd: float
    sunk_pct_of_deposit: float
    rent_escrow_pct_of_deposit: float
    max_allowed_sunk_pct: float
    breakdown: dict[str, float]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "placement": self.placement,
            "wide_range": self.wide_range,
            "literal_pool_ticks": self.literal_pool_ticks,
            "recoverable_sol_est": round(self.recoverable_sol_est, 6),
            "sunk_sol_est": round(self.sunk_sol_est, 6),
            "rent_escrow_sol": round(self.rent_escrow_sol, 6),
            "priority_and_base_sol": round(self.priority_and_base_sol, 6),
            "total_wallet_sol_est": round(self.total_wallet_sol_est, 6),
            "deposit_sol": round(self.deposit_sol, 6),
            "deposit_usd": round(self.deposit_usd, 2),
            "sol_price_usd": round(self.sol_price_usd, 2),
            "rent_escrow_usd": round(self.rent_escrow_usd, 2),
            "sunk_usd": round(self.sunk_usd, 2),
            "sunk_pct_of_deposit": round(self.sunk_pct_of_deposit, 1),
            "rent_escrow_pct_of_deposit": round(self.rent_escrow_pct_of_deposit, 1),
            "max_allowed_sunk_pct": round(self.max_allowed_sunk_pct, 1),
            "breakdown": {k: round(v, 6) for k, v in self.breakdown.items()},
            "notes": list(self.notes),
        }


def _placement_from_kwargs(open_kwargs: Mapping[str, Any] | None) -> str:
    if not open_kwargs:
        return "centered"
    if open_kwargs.get("literal_pool_full_range"):
        return "literal_pool"
    if is_wide_band_open_kwargs(open_kwargs) or open_kwargs.get("wide_range"):
        return "wide_band"
    side = open_kwargs.get("single_side")
    if side in ("above", "below"):
        return f"single_{side}"
    return "centered"


def _band_width_pct(open_kwargs: Mapping[str, Any] | None) -> float:
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


def estimate_open_rent_escrow(
    *,
    deposit_sol: float,
    open_kwargs: Mapping[str, Any] | None = None,
    settings: Any | None = None,
    priority_micro: int | None = None,
) -> RentEscrowEstimate:
    """Model SOL escrow for a planned open from style kwargs (no RPC simulation)."""

    cfg = fee_config_from_settings(settings)
    from raydium_lp1.fee_guard import estimate_clmm_open_cost_sol

    fee_est = estimate_clmm_open_cost_sol(cfg, deposit_sol=deposit_sol, priority_micro=priority_micro)
    pri_base = float(fee_est["priority_fee_sol"]) + float(fee_est["base_fee_sol"])

    kw = dict(open_kwargs or {})
    placement = _placement_from_kwargs(kw)
    literal = bool(kw.get("literal_pool_full_range"))
    wide = is_wide_band_open_kwargs(kw) or bool(kw.get("wide_range"))
    width = _band_width_pct(kw)

    recoverable = _RECOVERABLE_BASE_SOL + _NFT_ATA_EXTRA_SOL
    sunk = 0.0
    notes: list[str] = []

    if literal:
        sunk = _TICK_ARRAY_SUNK_SOL * 2.0
        notes.append("Literal pool min/max ticks: up to ~0.14 SOL may not return on close.")
    elif wide:
        if width >= 70:
            sunk = _TICK_ARRAY_SUNK_SOL * 0.55
            notes.append("Wide band (~80%): moderate tick-array risk; much less than literal full range.")
        else:
            sunk = _TICK_ARRAY_SUNK_SOL * 0.25
    elif placement.startswith("single_"):
        sunk = _TICK_ARRAY_SUNK_SOL * 0.15
        notes.append("Single-sided band: usually one new tick array near spot.")
    else:
        if width <= 25:
            sunk = _TICK_ARRAY_SUNK_SOL * 0.12
        elif width <= 45:
            sunk = _TICK_ARRAY_SUNK_SOL * 0.22
        else:
            sunk = _TICK_ARRAY_SUNK_SOL * 0.35
        notes.append("Centered band: sunk rent rises with width (edge tick arrays).")

    recoverable = min(recoverable, float(cfg.clmm_open_rent_sol))
    rent_escrow = recoverable + sunk
    total_wallet = rent_escrow + pri_base + _PRIORITY_BUFFER_SOL

    sol_px = float(cfg.sol_price_usd)
    dep = max(0.0, float(deposit_sol))
    dep_usd = dep * sol_px
    sunk_usd = sunk * sol_px
    escrow_usd = rent_escrow * sol_px
    sunk_pct = (100.0 * sunk_usd / dep_usd) if dep_usd > 0 else 999.0
    escrow_pct = (100.0 * escrow_usd / dep_usd) if dep_usd > 0 else 999.0
    max_pct = float(cfg.max_rent_escrow_pct_of_deposit)

    return RentEscrowEstimate(
        placement=placement,
        wide_range=wide,
        literal_pool_ticks=literal,
        recoverable_sol_est=recoverable,
        sunk_sol_est=sunk,
        rent_escrow_sol=rent_escrow,
        priority_and_base_sol=pri_base,
        total_wallet_sol_est=total_wallet,
        deposit_sol=dep,
        deposit_usd=dep_usd,
        sol_price_usd=sol_px,
        rent_escrow_usd=escrow_usd,
        sunk_usd=sunk_usd,
        sunk_pct_of_deposit=sunk_pct,
        rent_escrow_pct_of_deposit=escrow_pct,
        max_allowed_sunk_pct=max_pct,
        breakdown={
            "recoverable_sol": recoverable,
            "sunk_sol": sunk,
            "priority_fee_sol": float(fee_est["priority_fee_sol"]),
            "base_fee_sol": float(fee_est["base_fee_sol"]),
        },
        notes=tuple(notes),
    )


def assert_rent_escrow_allowed(
    *,
    deposit_sol: float,
    open_kwargs: Mapping[str, Any] | None = None,
    settings: Any | None = None,
    priority_micro: int | None = None,
) -> RentEscrowEstimate:
    """Raise if estimated sunk rent+escrow exceeds configured % of deposit."""

    cfg = fee_config_from_settings(settings)
    est = estimate_open_rent_escrow(
        deposit_sol=deposit_sol,
        open_kwargs=open_kwargs,
        settings=settings,
        priority_micro=priority_micro,
    )
    if not cfg.enabled:
        return est

    max_pct = float(cfg.max_rent_escrow_pct_of_deposit)
    if est.literal_pool_ticks:
        raise FeeGuardBlockedError(
            "Rent guard: literal pool min/max full range is disabled. "
            f"Estimated sunk rent ~{est.sunk_sol_est:.4f} SOL (~${est.sunk_usd:.2f}) — "
            "use standard_full_range (wide band max 80%) instead."
        )
    if est.sunk_pct_of_deposit > max_pct + 1e-9:
        raise FeeGuardBlockedError(
            f"Rent/escrow guard: estimated non-recoverable rent ~{est.sunk_pct_of_deposit:.1f}% "
            f"of deposit (max {max_pct:.1f}%). "
            f"Sunk ~{est.sunk_sol_est:.4f} SOL (~${est.sunk_usd:.2f}) on ~${est.deposit_usd:.2f} deposit. "
            f"Placement={est.placement}, band~{ _band_width_pct(open_kwargs) :.0f}% wide. "
            "Narrow the band, raise deposit size, or lower max_rent_escrow_pct_of_deposit in settings."
        )
    return est
