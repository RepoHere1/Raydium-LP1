"""Estimate CLMM open wallet SOL need — aligned with Raydium, not inflated escrow fiction.

**What Raydium actually does (same SDK path as ``open_position.mjs``):**
- Creates a position NFT + personal position state (~0.007–0.009 SOL). **Recoverable** on close/burn.
- Creates SPL ATAs only if missing (~0.002 SOL each, recoverable when closed).
- Creates **tick-array accounts only if they do not already exist** for that pool. Active pools
  already have arrays along the curve near spot — Raydium UI opens for **network fees + recoverable
  rent**, not ~0.15 SOL of “sunk” rent per click.

**What LP1 wrongly assumed before:**
- ``clmm_open_rent_sol=0.055`` treated as spent every open.
- ``0.072 SOL × 15–55%`` “sunk” tick arrays on every band shape regardless of pool state.
- ``max_rent_escrow_pct_of_deposit`` blocked micro deposits using that fiction.

Use ``lp_rent_conservative_estimates: true`` in settings only if you want the old pessimistic model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from raydium_lp1.fee_guard import FeeGuardBlockedError, fee_config_from_settings
from raydium_lp1.lp_full_range import (
    DEFAULT_WIDE_BAND_WIDTH_PCT,
    MAX_WIDE_BAND_WIDTH_PCT,
    is_wide_band_open_kwargs,
)

# Observed mainnet (lamports 2_039_280 + 2_394_240 + NFT ~2M) — returned on close
_RECOVERABLE_POSITION_SOL = 0.0075
_ATA_CREATE_SOL = 0.002039
# Per NEW tick array if SDK must init (72161280 lamports) — usually 0 on active pools
_TICK_ARRAY_NEW_SOL = 0.072131
_PRIORITY_BUFFER_SOL = 0.00002

# Legacy pessimistic multipliers (optional)
_TICK_ARRAY_SUNK_LEGACY = 0.072
_RECOVERABLE_LEGACY = 0.0055
_NFT_ATA_LEGACY = 0.002


@dataclass(frozen=True)
class RentEscrowEstimate:
    """Pre-trade rent / escrow outlook for one CLMM open."""

    placement: str
    wide_range: bool
    literal_pool_ticks: bool
    recoverable_sol_est: float
    sunk_sol_est: float
    new_tick_arrays_est: int
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
    rent_model: str
    breakdown: dict[str, float]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "placement": self.placement,
            "wide_range": self.wide_range,
            "literal_pool_ticks": self.literal_pool_ticks,
            "recoverable_sol_est": round(self.recoverable_sol_est, 6),
            "sunk_sol_est": round(self.sunk_sol_est, 6),
            "new_tick_arrays_est": self.new_tick_arrays_est,
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
            "rent_model": self.rent_model,
            "breakdown": {k: round(v, 6) for k, v in self.breakdown.items()},
            "notes": list(self.notes),
        }


def _rent_conservative_mode(settings: Any | None) -> bool:
    g = settings if isinstance(settings, dict) else {}
    return bool(g.get("lp_rent_conservative_estimates", False))


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


def _raydium_new_tick_arrays(
    placement: str,
    *,
    literal: bool,
    wide: bool,
    width_pct: float,
    pay_needs_ata: bool = False,
) -> int:
    """How many tick-array accounts the SDK might initialize (0 on typical active pools)."""

    if literal:
        return 2
    if wide and width_pct >= 75:
        return 0
    if placement.startswith("single_"):
        return 0
    if width_pct <= 50:
        return 0
    return 0


def _estimate_raydium(
    *,
    deposit_sol: float,
    kw: dict[str, Any],
    placement: str,
    literal: bool,
    wide: bool,
    width: float,
    fee_est: dict[str, Any],
    pri_base: float,
    cfg: Any,
    pay_needs_ata: bool = False,
) -> tuple[float, float, int, list[str]]:
    notes: list[str] = [
        "Raydium model: tick arrays near spot usually already exist — no 0.072 SOL charge.",
        "Position NFT + state rent is recoverable when you close/burn the position.",
    ]
    recoverable = _RECOVERABLE_POSITION_SOL
    if pay_needs_ata:
        recoverable += _ATA_CREATE_SOL
        notes.append("May create one SPL ATA (~0.002 SOL, recoverable if closed).")
    recoverable = min(recoverable, float(cfg.clmm_open_rent_sol) or recoverable)

    n_arrays = _raydium_new_tick_arrays(
        placement, literal=literal, wide=wide, width_pct=width, pay_needs_ata=pay_needs_ata
    )
    sunk = n_arrays * _TICK_ARRAY_NEW_SOL
    if n_arrays:
        notes.append(
            f"Worst case: {n_arrays} new tick-array account(s) if pool has none at range edge "
            f"(~{_TICK_ARRAY_NEW_SOL:.4f} SOL each); active pools usually 0."
        )
    return recoverable, sunk, n_arrays, notes


def _estimate_legacy(
    *,
    placement: str,
    literal: bool,
    wide: bool,
    width: float,
    cfg: Any,
) -> tuple[float, float, int, list[str]]:
    notes: list[str] = ["Legacy conservative rent model (lp_rent_conservative_estimates=true)."]
    recoverable = _RECOVERABLE_LEGACY + _NFT_ATA_LEGACY
    sunk = 0.0
    if literal:
        sunk = _TICK_ARRAY_SUNK_LEGACY * 2.0
        notes.append("Literal pool min/max ticks: up to ~0.14 SOL may not return on close.")
    elif wide:
        sunk = _TICK_ARRAY_SUNK_LEGACY * (0.55 if width >= 70 else 0.25)
    elif placement.startswith("single_"):
        sunk = _TICK_ARRAY_SUNK_LEGACY * 0.15
    else:
        sunk = _TICK_ARRAY_SUNK_LEGACY * (0.12 if width <= 25 else 0.22 if width <= 45 else 0.35)
    recoverable = min(recoverable, float(cfg.clmm_open_rent_sol))
    n_arrays = 2 if literal else (1 if sunk >= _TICK_ARRAY_SUNK_LEGACY * 0.4 else 0)
    return recoverable, sunk, n_arrays, notes


def estimate_open_rent_escrow(
    *,
    deposit_sol: float,
    open_kwargs: Mapping[str, Any] | None = None,
    settings: Any | None = None,
    priority_micro: int | None = None,
    pay_needs_ata: bool = False,
) -> RentEscrowEstimate:
    """Model SOL needed for a planned open (recoverable vs truly sunk)."""

    cfg = fee_config_from_settings(settings)
    from raydium_lp1.fee_guard import estimate_clmm_open_cost_sol

    fee_est = estimate_clmm_open_cost_sol(cfg, deposit_sol=deposit_sol, priority_micro=priority_micro)
    pri_base = float(fee_est["priority_fee_sol"]) + float(fee_est["base_fee_sol"])

    kw = dict(open_kwargs or {})
    placement = _placement_from_kwargs(kw)
    literal = bool(kw.get("literal_pool_full_range"))
    wide = is_wide_band_open_kwargs(kw) or bool(kw.get("wide_range"))
    width = _band_width_pct(kw)

    if _rent_conservative_mode(settings):
        recoverable, sunk, n_arrays, notes = _estimate_legacy(
            placement=placement, literal=literal, wide=wide, width=width, cfg=cfg
        )
        model = "conservative"
    else:
        recoverable, sunk, n_arrays, notes = _estimate_raydium(
            deposit_sol=deposit_sol,
            kw=kw,
            placement=placement,
            literal=literal,
            wide=wide,
            width=width,
            fee_est=fee_est,
            pri_base=pri_base,
            cfg=cfg,
            pay_needs_ata=pay_needs_ata,
        )
        model = "raydium"

    rent_escrow = recoverable + sunk
    total_wallet = rent_escrow + pri_base + _PRIORITY_BUFFER_SOL

    sol_px = float(cfg.sol_price_usd)
    dep = max(0.0, float(deposit_sol))
    dep_usd = dep * sol_px
    sunk_usd = sunk * sol_px
    escrow_usd = rent_escrow * sol_px
    sunk_pct = (100.0 * sunk_usd / dep_usd) if dep_usd > 0 else (0.0 if sunk <= 0 else 999.0)
    escrow_pct = (100.0 * escrow_usd / dep_usd) if dep_usd > 0 else 999.0
    max_pct = float(cfg.max_rent_escrow_pct_of_deposit)

    return RentEscrowEstimate(
        placement=placement,
        wide_range=wide,
        literal_pool_ticks=literal,
        recoverable_sol_est=recoverable,
        sunk_sol_est=sunk,
        new_tick_arrays_est=n_arrays,
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
        rent_model=model,
        breakdown={
            "recoverable_sol": recoverable,
            "sunk_sol": sunk,
            "new_tick_arrays": float(n_arrays),
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
    pay_needs_ata: bool = False,
) -> RentEscrowEstimate:
    """Raise only on literal full range or material *sunk* rent vs deposit cap."""

    cfg = fee_config_from_settings(settings)
    est = estimate_open_rent_escrow(
        deposit_sol=deposit_sol,
        open_kwargs=open_kwargs,
        settings=settings,
        priority_micro=priority_micro,
        pay_needs_ata=pay_needs_ata,
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

    # Only block when there is meaningful sunk rent (new tick arrays), not recoverable escrow
    material_sunk_sol = 0.004
    if est.sunk_sol_est > material_sunk_sol and est.sunk_pct_of_deposit > max_pct + 1e-9:
        raise FeeGuardBlockedError(
            f"Rent guard: estimated non-recoverable rent ~{est.sunk_pct_of_deposit:.1f}% "
            f"of deposit (max {max_pct:.1f}%). "
            f"Sunk ~{est.sunk_sol_est:.4f} SOL (~${est.sunk_usd:.2f}) on ~${est.deposit_usd:.2f} deposit. "
            f"Placement={est.placement}, band~{ _band_width_pct(open_kwargs) :.0f}% wide. "
            "Narrow the band, use a busier pool, or lower max_rent_escrow_pct_of_deposit in settings."
        )
    return est
