"""SPEND LESS=GET MORE — pre/post CLMM open cost planner (rent, wallet, style).

Hardwired before every LIVE open and detective LIVE top-pick: estimate sunk rent,
wallet headroom, and affordable deposit; optionally clamp deposit and fall back from
wide band to single-sided when micro deposits cannot pass the rent cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from raydium_lp1.fee_guard import FeeGuardBlockedError, assert_clmm_open_allowed, fee_config_from_settings
from raydium_lp1.no_escrow_policy import SUNK_RENT_EPSILON_SOL, normalize_settings_no_escrow
from raydium_lp1.lp_full_range import is_wide_band_open_kwargs, open_kwargs_for_wide_band
from raydium_lp1.lp_order_strategies import (
    STRATEGY_ASYMMETRIC,
    STRATEGY_BRAINIAC_CURSOR_SUCCESS,
    STRATEGY_FULL_RANGE,
)
from raydium_lp1.lp_rent_escrow import RentEscrowEstimate, estimate_open_rent_escrow

TAG = "SPEND LESS=GET MORE"

# Centered/straddle needs two legs + swap; single-sided one leg is cheaper on SOL/alt.
_FALLBACK_STRATEGY_SOL_ALT = STRATEGY_ASYMMETRIC


@dataclass(frozen=True)
class SpendLessConfig:
    enabled: bool = True
    auto_clamp_deposit: bool = True
    auto_fallback_from_wide: bool = True
    on_chain_rent_buffer_sol: float = 0.012
    min_deposit_usd_floor: float = 0.25

    @classmethod
    def from_settings(cls, settings: Any | None) -> SpendLessConfig:
        g = normalize_settings_no_escrow(settings)

        def _b(key: str, default: bool) -> bool:
            return bool(g.get(key, default))

        def _f(key: str, default: float) -> float:
            return float(g.get(key, default))

        return cls(
            enabled=_b("spend_less_get_more_enabled", True),
            auto_clamp_deposit=_b("spend_less_auto_clamp_deposit", True),
            auto_fallback_from_wide=_b("spend_less_auto_fallback_from_wide", True),
            on_chain_rent_buffer_sol=max(0.0, _f("spend_less_on_chain_rent_buffer_sol", 0.012)),
            min_deposit_usd_floor=max(0.0, _f("spend_less_min_deposit_usd_floor", 0.25)),
        )


@dataclass
class SpendLessPlan:
    """Outcome of pre-open SPEND LESS=GET MORE analysis."""

    ok: bool
    blocked: bool
    tag: str = TAG
    requested_deposit_usd: float = 0.0
    effective_deposit_usd: float = 0.0
    effective_deposit_sol: float = 0.0
    clamped: bool = False
    strategy_override: str | None = None
    open_kwargs_effective: dict[str, Any] = field(default_factory=dict)
    balance_sol: float = 0.0
    max_deposit_usd_wallet: float = 0.0
    max_deposit_usd_rent_cap: float = 0.0
    min_deposit_usd_rent_cap: float = 0.0
    sol_need_est: float = 0.0
    rent_escrow: dict[str, Any] = field(default_factory=dict)
    block_reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "ok": self.ok,
            "blocked": self.blocked,
            "requested_deposit_usd": round(self.requested_deposit_usd, 2),
            "effective_deposit_usd": round(self.effective_deposit_usd, 2),
            "effective_deposit_sol": round(self.effective_deposit_sol, 6),
            "clamped": self.clamped,
            "strategy_override": self.strategy_override,
            "balance_sol": round(self.balance_sol, 6),
            "max_deposit_usd_wallet": round(self.max_deposit_usd_wallet, 2),
            "max_deposit_usd_rent_cap": round(self.max_deposit_usd_rent_cap, 2),
            "min_deposit_usd_rent_cap": round(self.min_deposit_usd_rent_cap, 2),
            "sol_need_est": round(self.sol_need_est, 6),
            "rent_escrow": self.rent_escrow,
            "block_reasons": list(self.block_reasons),
            "recommendations": list(self.recommendations),
            "notes": list(self.notes),
        }


def _rent_est(
    deposit_sol: float,
    open_kwargs: Mapping[str, Any],
    settings: Any,
    *,
    pay_needs_ata: bool = False,
) -> RentEscrowEstimate:
    return estimate_open_rent_escrow(
        deposit_sol=deposit_sol,
        open_kwargs=open_kwargs,
        settings=settings,
        pay_needs_ata=pay_needs_ata,
    )


def _min_deposit_usd_for_rent_cap(
    open_kwargs: Mapping[str, Any],
    *,
    settings: Any,
    sol_price_usd: float,
    max_pct: float,
    ceiling_usd: float = 500.0,
) -> float | None:
    """Smallest deposit (USD) where sunk rent % <= max_pct for this band shape."""

    sunk_sol = float(
        _rent_est(1.0 / sol_price_usd, open_kwargs, settings).sunk_sol_est
    )
    if sunk_sol <= 0:
        return 0.0
    min_usd = (100.0 * sunk_sol * sol_price_usd) / max_pct
    return min_usd if min_usd <= ceiling_usd else None


def _max_deposit_usd_rent_cap(
    open_kwargs: Mapping[str, Any],
    *,
    settings: Any,
    sol_price_usd: float,
    ceiling_usd: float = 500.0,
) -> float:
    """Largest deposit still under rent cap (sunk % monotonic down as deposit rises)."""

    max_pct = float(fee_config_from_settings(settings).max_rent_escrow_pct_of_deposit)
    min_usd = _min_deposit_usd_for_rent_cap(
        open_kwargs, settings=settings, sol_price_usd=sol_price_usd, max_pct=max_pct, ceiling_usd=ceiling_usd
    )
    if min_usd is None:
        return 0.0
    return ceiling_usd


def _max_deposit_usd_wallet(
    *,
    balance_sol: float,
    reserve_sol: float,
    rent_total_sol: float,
    rent_buffer_sol: float,
    pay_is_sol: bool,
    sol_price_usd: float,
) -> float:
    if not pay_is_sol or sol_price_usd <= 0:
        return 500.0
    headroom = max(0.0, balance_sol - reserve_sol - rent_total_sol - rent_buffer_sol)
    return headroom * sol_price_usd


def _sol_need(
    *,
    deposit_sol: float,
    rent_total_sol: float,
    reserve_sol: float,
    rent_buffer_sol: float,
    pay_is_sol: bool,
) -> float:
    need = reserve_sol + rent_total_sol + rent_buffer_sol
    if pay_is_sol:
        need += deposit_sol
    return need


def _wide_fallback_kwargs(open_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Drop wide band flags; caller should merge with asymmetric plan separately."""

    kw = dict(open_kwargs)
    for key in ("wide_range", "full_range", "literal_pool_full_range", "wide_range_width_pct"):
        kw.pop(key, None)
    kw["single_side"] = "above"
    kw.setdefault("single_side_width_pct", 20.0)
    kw.setdefault("band_tick_steps", 15)
    return kw


def analyze_open_plan(
    *,
    requested_deposit_usd: float,
    open_kwargs: Mapping[str, Any],
    pay_symbol: str,
    balance_sol: float,
    reserve_sol: float,
    settings: Any | None = None,
    strategy_id: str | None = None,
    sol_price_usd: float | None = None,
) -> SpendLessPlan:
    """Plan an open under rent cap + wallet headroom; may propose clamp (no wide fallback)."""

    settings = normalize_settings_no_escrow(settings)
    sl_cfg = SpendLessConfig.from_settings(settings)
    fee_cfg = fee_config_from_settings(settings)
    px = float(sol_price_usd or fee_cfg.sol_price_usd or 180.0)
    pay_sym = str(pay_symbol or "SOL").upper()
    pay_is_sol = pay_sym in ("SOL", "WSOL")
    pay_needs_ata = not pay_is_sol
    req = max(0.0, float(requested_deposit_usd))
    kw = dict(open_kwargs)
    blocks: list[str] = []
    recs: list[str] = []
    notes: list[str] = []

    if not sl_cfg.enabled:
        dep_sol = req / px if px > 0 else 0.0
        est = _rent_est(dep_sol, kw, settings, pay_needs_ata=pay_needs_ata)
        return SpendLessPlan(
            ok=True,
            blocked=False,
            requested_deposit_usd=req,
            effective_deposit_usd=req,
            effective_deposit_sol=dep_sol,
            balance_sol=balance_sol,
            rent_escrow=est.to_dict(),
            open_kwargs_effective=kw,
            notes=["SPEND LESS=GET MORE disabled in settings."],
        )

    max_pct = float(fee_cfg.max_rent_escrow_pct_of_deposit)
    dep_sol_req = req / px if px > 0 else 0.0
    est_req = _rent_est(dep_sol_req, kw, settings, pay_needs_ata=pay_needs_ata)
    rent_total = float(est_req.total_wallet_sol_est)
    buffer = sl_cfg.on_chain_rent_buffer_sol if pay_is_sol else 0.003

    min_usd_rent = _min_deposit_usd_for_rent_cap(kw, settings=settings, sol_price_usd=px, max_pct=max_pct) or 0.0
    max_usd_wallet = _max_deposit_usd_wallet(
        balance_sol=balance_sol,
        reserve_sol=reserve_sol,
        rent_total_sol=rent_total,
        rent_buffer_sol=buffer,
        pay_is_sol=pay_is_sol,
        sol_price_usd=px,
    )
    max_usd_rent = _max_deposit_usd_rent_cap(kw, settings=settings, sol_price_usd=px)

    wide = is_wide_band_open_kwargs(kw) or (strategy_id or "").strip() == STRATEGY_FULL_RANGE
    if wide and min_usd_rent > 1.0 and req + 1e-9 < min_usd_rent:
        recs.append(
            f"Wide band may need ~${min_usd_rent:.0f}+ deposit if pool must create new tick arrays "
            f"(~${est_req.sunk_usd:.2f} sunk est. on ${req:.2f})."
        )

    effective_usd = req
    effective_kw = dict(kw)
    strat_override: str | None = None
    clamped = False

    brainiac_order = (strategy_id or "").strip() == STRATEGY_BRAINIAC_CURSOR_SUCCESS

    # Style fallback: wide → single-sided SOL deposit when rent cap blocks micro wide opens.
    if (
        sl_cfg.auto_fallback_from_wide
        and wide
        and not brainiac_order
        and req + 1e-9 < min_usd_rent
        and pay_is_sol
    ):
        fb_kw = _wide_fallback_kwargs(kw)
        min_fb = _min_deposit_usd_for_rent_cap(fb_kw, settings=settings, sol_price_usd=px, max_pct=max_pct) or 0.0
        if req + 1e-9 >= min_fb:
            effective_kw = fb_kw
            strat_override = _FALLBACK_STRATEGY_SOL_ALT
            notes.append(
                f"Fallback: {STRATEGY_FULL_RANGE} wide → {_FALLBACK_STRATEGY_SOL_ALT} single-sided "
                f"(saves alt-leg swap + lower sunk rent)."
            )
            min_usd_rent = min_fb
            est_req = _rent_est(req / px, effective_kw, settings, pay_needs_ata=pay_needs_ata)
            rent_total = float(est_req.total_wallet_sol_est)

    affordable = min(max_usd_wallet, max_usd_rent) if max_usd_rent > 0 else max_usd_wallet
    if sl_cfg.auto_clamp_deposit and req > affordable + 1e-9 and affordable >= sl_cfg.min_deposit_usd_floor:
        effective_usd = affordable
        clamped = True
        notes.append(f"Clamped deposit ${req:.2f} → ${effective_usd:.2f} (wallet + rent cap).")

    if effective_usd + 1e-9 < sl_cfg.min_deposit_usd_floor:
        blocks.append(
            f"Deposit ${effective_usd:.2f} below floor ${sl_cfg.min_deposit_usd_floor:.2f}."
        )

    dep_sol_eff = effective_usd / px if px > 0 else 0.0
    est_eff = _rent_est(dep_sol_eff, effective_kw, settings, pay_needs_ata=pay_needs_ata)
    if est_eff.literal_pool_ticks:
        blocks.append("NO ESCROW PAID: literal pool full range is disabled (use wide band max 80%).")
    elif est_eff.sunk_sol_est > SUNK_RENT_EPSILON_SOL or est_eff.new_tick_arrays_est > 0:
        blocks.append(
            f"NO ESCROW PAID: band may require new tick-array rent "
            f"(~{est_eff.sunk_sol_est:.4f} SOL sunk est. on ${effective_usd:.2f} deposit). "
            "Use a busier pool or narrower band."
        )

    sol_need = _sol_need(
        deposit_sol=dep_sol_eff,
        rent_total_sol=float(est_eff.total_wallet_sol_est),
        reserve_sol=reserve_sol,
        rent_buffer_sol=buffer,
        pay_is_sol=pay_is_sol,
    )
    if pay_is_sol and balance_sol + 1e-9 < sol_need:
        blocks.append(
            f"Wallet {balance_sol:.4f} SOL < need ~{sol_need:.4f} SOL "
            f"(deposit {dep_sol_eff:.4f} + rent ~{est_eff.total_wallet_sol_est:.4f} + buffer {buffer:.4f})."
        )
        recs.append("Top up SOL (~0.02+ for USDC-pay opens, more if deposit is SOL).")

    if not pay_is_sol:
        min_sol_headroom = float(est_eff.recoverable_sol_est) + buffer + 0.008
        if balance_sol + 1e-9 < min_sol_headroom:
            blocks.append(
                f"USDC/alt pay: wallet SOL {balance_sol:.4f} < ~{min_sol_headroom:.3f} "
                f"for position rent (~{est_eff.recoverable_sol_est:.4f} SOL recoverable on close) + tx fees."
            )
            recs.append("Keep ~0.02–0.03 SOL; Raydium does not need 0.14 SOL for a normal open.")

    if est_eff.sunk_pct_of_deposit > max_pct * 0.85:
        recs.append(
            "Keep priority fee at 2000 micro-lamports unless the network is congested."
        )
    if not blocks and wide and effective_usd >= min_usd_rent:
        recs.append("Wide band: acceptable sunk rent vs deposit at this size.")
    if strat_override:
        recs.append("Pre-fund pay token in-wallet to avoid a second Jupiter funding tx.")

    ok = not blocks and effective_usd >= sl_cfg.min_deposit_usd_floor
    return SpendLessPlan(
        ok=ok,
        blocked=bool(blocks),
        requested_deposit_usd=req,
        effective_deposit_usd=effective_usd,
        effective_deposit_sol=dep_sol_eff,
        clamped=clamped,
        strategy_override=strat_override,
        open_kwargs_effective=effective_kw,
        balance_sol=balance_sol,
        max_deposit_usd_wallet=max_usd_wallet,
        max_deposit_usd_rent_cap=max_usd_rent,
        min_deposit_usd_rent_cap=min_usd_rent,
        sol_need_est=sol_need,
        rent_escrow=est_eff.to_dict(),
        block_reasons=blocks,
        recommendations=recs,
        notes=notes,
    )


def enforce_open_plan(
    plan: SpendLessPlan,
) -> None:
    """Raise FeeGuardBlockedError when SPEND LESS blocks the open."""

    if plan.ok:
        return
    msg = f"{TAG}: " + "; ".join(plan.block_reasons[:3])
    if plan.recommendations:
        msg += " | " + plan.recommendations[0]
    raise FeeGuardBlockedError(msg)


def _pool_and_style_from_pick(pick: Mapping[str, Any], scanner: Any, strategy_id: str):
    from dataclasses import replace

    from raydium_lp1.lp_open_style import resolve_live_open_style
    from raydium_lp1.scanner import ScannerConfig

    pair = str(pick.get("pair") or "SOL/USDC")
    parts = pair.split("/")
    pool = {
        "id": pick.get("pool_id"),
        "mint_a_symbol": parts[0] if parts else "SOL",
        "mint_b_symbol": parts[-1] if parts else "USDC",
    }
    if isinstance(scanner, ScannerConfig):
        cfg = scanner
    else:
        from pathlib import Path

        cfg = ScannerConfig.from_file(Path(__file__).resolve().parents[2] / "config" / "settings.json")
    cfg = replace(cfg, lp_active_strategy=strategy_id)
    style = resolve_live_open_style(cfg, pool)
    return pool, style


def attach_post_open_analysis(
    result: dict[str, Any],
    *,
    plan: SpendLessPlan | None,
    deposit_usd: float | None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """Add on-chain cost breakdown + SPEND LESS notes to an open result."""

    out = dict(result)
    out["spend_less_get_more"] = plan.to_dict() if plan else {"tag": TAG}
    if not out.get("ok"):
        return out
    try:
        from raydium_lp1.lp_tx_cost_analysis import analyze_open_bundle
        from raydium_lp1.raydium_clmm import wallet_balance

        wb = wallet_balance()
        fee_est = (out.get("clmm") or {}).get("fee_guard_estimate") or out.get("fee_guard_estimate") or {}
        rent = fee_est.get("rent_escrow") if isinstance(fee_est, dict) else plan.rent_escrow if plan else None
        dep = deposit_usd if deposit_usd is not None else (plan.effective_deposit_usd if plan else None)
        out["spend_less_cost_analysis"] = analyze_open_bundle(
            out,
            wallet=str(wb.get("address") or ""),
            rpc_url=str(wb.get("rpc_url") or ""),
            rent_escrow_estimate=rent,
            deposit_usd=dep,
        )
    except Exception as exc:
        out["spend_less_cost_analysis_error"] = str(exc)
    return out


def annotate_brainiac_pick(
    pick: Mapping[str, Any],
    *,
    deposit_usd: float,
    balance_sol: float,
    reserve_sol: float,
    settings: Any | None,
    scanner: Any,
) -> dict[str, Any]:
    """Attach SPEND LESS plan to a detective top_pick row (scan UI)."""

    row = dict(pick)
    best = row.get("best_strategy") if isinstance(row.get("best_strategy"), dict) else {}
    sid = str(best.get("strategy_id") or "auto_volatility_pick")
    _, style = _pool_and_style_from_pick(row, scanner, sid)
    pay = str(row.get("pay_symbol") or style.open_kwargs.get("pay_symbol") or "USDC").upper()
    plan = analyze_open_plan(
        requested_deposit_usd=float(deposit_usd),
        open_kwargs=style.open_kwargs,
        pay_symbol=pay,
        balance_sol=balance_sol,
        reserve_sol=reserve_sol,
        settings=settings,
        strategy_id=sid,
    )
    row["spend_less_get_more"] = plan.to_dict()
    row["open_affordable"] = plan.ok
    if not plan.ok:
        row["spend_less_block_summary"] = "; ".join(plan.block_reasons[:2])
    return row


def prepare_brainiac_live_open(
    pick: Mapping[str, Any],
    *,
    deposit_usd: float,
    balance_sol: float,
    reserve_sol: float,
    settings: Any | None,
    scanner: Any,
) -> tuple[SpendLessPlan, str, float | None]:
    """Return (plan, strategy_id, effective_deposit_usd) for execute_brainiac_open."""

    best = pick.get("best_strategy") if isinstance(pick.get("best_strategy"), dict) else {}
    sid = str(best.get("strategy_id") or "auto_volatility_pick")
    _, style = _pool_and_style_from_pick(pick, scanner, sid)
    pay = str(pick.get("pay_symbol") or style.open_kwargs.get("pay_symbol") or "USDC").upper()

    plan = analyze_open_plan(
        requested_deposit_usd=float(deposit_usd),
        open_kwargs=style.open_kwargs,
        pay_symbol=pay,
        balance_sol=balance_sol,
        reserve_sol=reserve_sol,
        settings=settings,
        strategy_id=sid,
    )
    if plan.strategy_override:
        sid = plan.strategy_override
        _, style = _pool_and_style_from_pick(pick, scanner, sid)
        plan = analyze_open_plan(
            requested_deposit_usd=float(deposit_usd),
            open_kwargs=plan.open_kwargs_effective,
            pay_symbol=pay,
            balance_sol=balance_sol,
            reserve_sol=reserve_sol,
            settings=settings,
            strategy_id=sid,
        )
    eff_dep = plan.effective_deposit_usd if plan.ok else None
    return plan, sid, eff_dep
