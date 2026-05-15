"""Paper-only CLMM / concentrated LP band suggestions from live Raydium pool data.

This module does **not** build transactions, sign, or open positions. It turns
the same public metrics the scanner already has (TVL, volume, nested ``day`` price
min/max when present, momentum + detective blobs) into **human-auditable** lower /
upper price ideas and parallel full-range budget splits.

Real money requires: reading the **exact** on-chain sqrt price & tick spacing for
the pool program, slippage-protected swap + add-liquidity instructions, and robust
failure handling — that lives outside this heuristic layer.

See docs/LP_PLACEMENT.md for the execution gap checklist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from raydium_lp1 import lp_slots


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _pool_raw(pool: Mapping[str, Any]) -> dict[str, Any]:
    raw = pool.get("raw")
    return raw if isinstance(raw, dict) else {}


def spot_price_quote_per_base(pool: Mapping[str, Any]) -> tuple[float | None, str]:
    """Best-effort reference price (quote units per 1 base) from Raydium ``day`` block.

    Many list responses omit prices; ``priceMin`` / ``priceMax`` are used when present
    as a mid estimate. Falls back to ``None`` — caller still gets width/skew guidance.
    """

    raw = _pool_raw(pool)
    day = raw.get("day")
    if not isinstance(day, dict):
        return None, "no_day_block"
    pmin = float(day.get("priceMin") or 0)
    pmax = float(day.get("priceMax") or 0)
    if pmin > 0 and pmax > 0:
        return (pmin + pmax) / 2.0, "day_price_min_max_mid"
    # Rare flat keys seen on some payloads
    for key in ("price", "mintPrice", "defaultQuotePrice"):
        v = raw.get(key)
        if isinstance(v, (int, float)) and float(v) > 0:
            return float(v), key
    return None, "no_price_fields"


def is_clmm_style_pool(pool: Mapping[str, Any]) -> bool:
    t = str(pool.get("type") or "").lower()
    subs = pool.get("subtypes") if isinstance(pool.get("subtypes"), list) else []
    blob = " ".join(str(s).lower() for s in subs)
    return "concentrated" in t or "clmm" in blob


def momentum_skew(momentum: Mapping[str, Any] | None, *, use_momentum: bool) -> tuple[float, list[str]]:
    """Map momentum / detective cues to [-1, 1] skew (positive = bias band upward)."""

    notes: list[str] = []
    if not use_momentum or not momentum:
        return 0.0, notes
    det = momentum.get("detective")
    if isinstance(det, dict):
        bias = float(det.get("inflow_bias") or 0)
        sk = _clamp(bias / 55.0, -1.0, 1.0)
        notes.append(f"inflow_bias->{sk:.2f}")
        sniff = det.get("sniff_tags")
        if isinstance(sniff, list):
            tags = set(str(x) for x in sniff)
            if "volume_surging_vs_7d" in tags or "volume_accelerating" in tags:
                sk = _clamp(sk + 0.12, -1.0, 1.0)
                notes.append("surge:+0.12")
    tier = str(momentum.get("tier") or "")
    if tier == "exit_now":
        sk = _clamp(sk - 0.35, -1.0, 1.0)
        notes.append("tier_exit_adjust")
    return sk, notes


def pick_width_pct(
    pool: Mapping[str, Any],
    momentum: Mapping[str, Any] | None,
    *,
    candidates: tuple[float, ...],
    default_pct: float,
    mode: str,
    risk_profile: str,
) -> tuple[float, str]:
    """Choose band width %. ``mode`` auto|symmetric."""

    mode_l = (mode or "auto").strip().lower()
    if mode_l in {"symmetric", "fixed", "popular_20", "manual_default"}:
        return default_pct, f"fixed:{mode_l}"

    cands = sorted({float(x) for x in candidates if float(x) > 0}) or (
        12.0,
        20.0,
        30.0,
        50.0,
    )
    raw = _pool_raw(pool)
    day = raw.get("day") if isinstance(raw.get("day"), dict) else {}
    pmin = float(day.get("priceMin") or 0)
    pmax = float(day.get("priceMax") or 0)
    swing = ((pmax - pmin) / pmin * 100.0) if pmin > 0 and pmax > pmin else 0.0

    vol = float(pool.get("volume_24h_usd") or 0)
    tvl = float(pool.get("liquidity_usd") or 0)
    churn = vol / tvl if tvl > 0 else 0.0

    # Wider bands when/day range is chaotic or churn is enormous (fee capture vs IL trade-off).
    target = float(default_pct)
    if swing > 40 or churn > 4.0:
        target = max(target, 35.0)
    elif swing > 20 or churn > 2.0:
        target = max(target, 25.0)
    elif swing < 8 and churn < 0.8:
        target = min(target, 20.0)

    if risk_profile.strip().lower() == "degen":
        target = min(55.0, target * 1.15)

    # Snap to nearest allowed candidate.
    nearest = min(cands, key=lambda w: abs(w - target))
    rationale = (
        f"auto:swing≈{swing:.1f}% churn≈{churn:.2f} tgt≈{target:.1f}% pick={nearest} "
        f"(candidates={list(cands)})"
    )
    return nearest, rationale


def asymmetric_quote_band(spot: float, width_pct: float, skew: float) -> tuple[float, float]:
    """Linear quote-per-base band; total fractional width ~= width_pct/100."""

    w = width_pct / 100.0
    sk = _clamp(skew, -1.0, 1.0)
    down_share = 0.5 - 0.25 * sk
    lo = spot * (1 - w * down_share)
    hi = spot * (1 + w * (1.0 - down_share))
    if lo <= 0 or hi <= lo:
        pad = spot * max(1e-9, w * 0.5)
        lo, hi = max(spot - pad, 1e-18), spot + pad
    return lo, hi


@dataclass(frozen=True)
class LPPlannerConfig:
    enabled: bool = False
    range_mode: str = "auto"
    default_width_pct: float = 20.0
    width_candidates: tuple[float, ...] = (12.0, 20.0, 30.0, 50.0)
    skew_use_momentum: bool = True
    full_range_parallel: bool = False
    full_range_budget_fraction: float = 0.25
    main_budget_fraction: float = 0.75
    max_lps_per_mint: int = 2
    risk_profile: str = "balanced"


def planner_config_from_scanner(config: Any) -> LPPlannerConfig:
    w = getattr(config, "lp_range_width_candidates", (12.0, 20.0, 30.0, 50.0))
    if isinstance(w, list):
        w = tuple(float(x) for x in w)
    return LPPlannerConfig(
        enabled=bool(getattr(config, "lp_planning_enabled", False)),
        range_mode=str(getattr(config, "lp_range_mode", "auto")),
        default_width_pct=float(getattr(config, "lp_default_range_width_pct", 20.0)),
        width_candidates=w if isinstance(w, tuple) and w else (12.0, 20.0, 30.0, 50.0),
        skew_use_momentum=bool(getattr(config, "lp_skew_use_momentum", True)),
        full_range_parallel=bool(getattr(config, "lp_full_range_parallel", False)),
        full_range_budget_fraction=_clamp(float(getattr(config, "lp_full_range_budget_fraction", 0.25)), 0.0, 1.0),
        main_budget_fraction=_clamp(float(getattr(config, "lp_main_budget_fraction", 0.75)), 0.0, 1.0),
        max_lps_per_mint=max(1, int(getattr(config, "lp_max_positions_per_mint", 2))),
        risk_profile=str(getattr(config, "risk_profile", "balanced")),
    )


def plan_for_pool(pool: Mapping[str, Any], momentum: Mapping[str, Any] | None, lp_cfg: LPPlannerConfig) -> dict[str, Any]:
    spot, spot_src = spot_price_quote_per_base(pool)
    skew, skew_notes = momentum_skew(momentum, use_momentum=lp_cfg.skew_use_momentum)
    width_pct, width_note = pick_width_pct(
        pool,
        momentum,
        candidates=lp_cfg.width_candidates,
        default_pct=lp_cfg.default_width_pct,
        mode=lp_cfg.range_mode,
        risk_profile=lp_cfg.risk_profile,
    )

    clmmish = is_clmm_style_pool(pool)
    concentrated: dict[str, Any]
    if spot is None:
        el, eh = asymmetric_quote_band(1.0, width_pct, skew)
        concentrated = {
            "style": "concentrated_synthetic",
            "note": (
                "No spot in Raydium list payload — use RPC sqrt_price & tick_spacing before trading."
            ),
            "width_pct": round(width_pct, 2),
            "width_choice": width_note,
            "skew": round(skew, 3),
            "skew_notes": skew_notes,
            "example_quote_band_if_spot_is_1": {
                "lower_quote_per_base": round(el, 8),
                "upper_quote_per_base": round(eh, 8),
            },
        }
    else:
        lo, hi = asymmetric_quote_band(spot, width_pct, skew)
        concentrated = {
            "style": "concentrated_banded",
            "spot_quote_per_base": spot,
            "spot_source": spot_src,
            "width_pct": round(width_pct, 2),
            "width_choice": width_note,
            "skew": round(skew, 3),
            "skew_notes": skew_notes,
            "lower_quote_per_base": round(lo, 8),
            "upper_quote_per_base": round(hi, 8),
        }

    fracs = dict(
        main_budget_fraction=round(lp_cfg.main_budget_fraction, 3),
        full_range_budget_fraction=round(lp_cfg.full_range_budget_fraction, 3)
        if lp_cfg.full_range_parallel
        else 0.0,
    )

    parallel_full = (
        {
            "enabled": True,
            "role": "stability_hedge",
            "budget_fraction_of_position_sol": lp_cfg.full_range_budget_fraction,
            "note": (
                "Full-range CLMM / wide CPMM leg for pathological wicks. Expect lower fee APR. "
                "Still dry-run only in this build."
            ),
        }
        if lp_cfg.full_range_parallel
        else {"enabled": False}
    )

    return {
        "execution": "paper_plan_only",
        "pool_id": str(pool.get("id") or ""),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "engine_interpretation": (
            "CLMM-style concentrated band" if clmmish else "CPMM constant-product (naturally full-range); band is advisory"
        ),
        "is_clmm_style": clmmish,
        "concentrated": concentrated,
        "parallel_full_range": parallel_full,
        "budget_split": fracs,
        "policy": {**lp_slots.policy_note(max_per_mint=lp_cfg.max_lps_per_mint)},
        "disclaimer": (
            "Heuristic from public API fields — not a probability-of-profit guarantee. "
            "Live money needs on-chain price, tick math, and signed Raydium instructions."
        ),
    }
