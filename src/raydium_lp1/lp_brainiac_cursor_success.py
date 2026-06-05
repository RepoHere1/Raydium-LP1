"""BRAINIAC-CURSOR-SUCCESS-80%-SKEWED-WIDE-No ESCROW — reasoning-based CLMM order type.

This order type encodes **why** a procedure works (brainiac scoring, skew, rent, pay-type settlement),
not a script that replays one historical pool/ticker. Pair symbols are discovered at runtime.

Use ``lp_active_strategy = brainiac_cursor_success_80_skewed_no_escrow`` or
``open_clmm_with_brainiac_cursor_success()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[2]

# Settings / dashboard value (slug) — must match lp_order_strategies.STRATEGY_BRAINIAC_CURSOR_SUCCESS
STRATEGY_BRAINIAC_CURSOR_SUCCESS = "brainiac_cursor_success_80_skewed_no_escrow"
STRATEGY_OFFICIAL_NAME = "BRAINIAC-CURSOR-SUCCESS-80%-SKEWED-WIDE-No ESCROW"
STRATEGY_SHORT_LABEL = "Brainiac 80% skew"
PLACEMENT_BRAINIAC_SKEWED_WIDE = "brainiac_skewed_wide"

WIDE_WIDTH_PCT = 80.0

SYNOPSIS = (
    "Brainiac-placed 80% wide CLMM straddle: skew optimized for 24h price overlap, "
    "two-sided pay+non-pay inventory, pay-type-only settlement, recoverable rent only."
)

# Reasoning pillars (not step-by-step replay of one trade)
PLACEMENT_REASONING: tuple[str, ...] = (
    "Score the pool with SUPER-BRAINIAC; do not enter on headline APR alone.",
    "Hold total width at 80%; grid-search skew for max overlap with 24h min/max, not naive ±40%.",
    "Open two-sided straddle from wallet inventory; refuse pay-only fallback on wide bands.",
    "Use Raydium recoverable NFT rent; reject inflated tick-array escrow in fee guard.",
)

SETTLEMENT_REASONING: tuple[str, ...] = (
    "Resolve pay-type per pool (SOL/USDC/USDT) — that is the only sweep sink and funding source.",
    "The other pair token (any symbol) is non-pay: never sweep into it, never swap from it to fund.",
    "Stray SPL outside the pair consolidates into pay-type after each close/open.",
    "Native SOL for tx fees is separate from pay-type economics when pay-type is SOL.",
)

SETTLEMENT_MODULE = "raydium_lp1.lp_junk_to_pay"

# Defaults learned from successful LIVE opens (low fees, max skew overlap).
LIVE_AUTO_FUND_FRACTION_DEFAULT = 0.42
LIVE_AUTO_FUND_FRACTION_SMALL = 0.35
LIVE_AUTO_MIN_IN_RANGE_FACTOR = 0.55
LIVE_AUTO_WIDE_WIDTH_PCT = 80.0
# Skip Jupiter fund only when wallet already holds this fraction of target non-pay USD.
NON_PAY_WALLET_COVERAGE_RATIO = 0.75


@dataclass
class BrainiacLiveAutoPolicy:
    """Executable knobs the order type applies without manual wizard tuning."""

    fund_non_pay_fraction: float = LIVE_AUTO_FUND_FRACTION_SMALL
    skip_fund_swap: bool = False
    skip_settle_after: bool = False
    reset_fee_session: bool = False
    run_pretrade: bool = True
    min_in_range_factor: float = LIVE_AUTO_MIN_IN_RANGE_FACTOR
    pre_live_consensus_scans: int = 5
    pre_live_scan_delay_sec: float = 2.0
    wide_width_pct: float = LIVE_AUTO_WIDE_WIDTH_PCT
    band_tick_steps_cap: int = 32
    apply_brainiac_strategy: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_non_pay_fraction": self.fund_non_pay_fraction,
            "skip_fund_swap": self.skip_fund_swap,
            "skip_settle_after": self.skip_settle_after,
            "reset_fee_session": self.reset_fee_session,
            "run_pretrade": self.run_pretrade,
            "min_in_range_factor": self.min_in_range_factor,
            "pre_live_consensus_scans": self.pre_live_consensus_scans,
            "pre_live_scan_delay_sec": self.pre_live_scan_delay_sec,
            "wide_width_pct": self.wide_width_pct,
            "band_tick_steps_cap": self.band_tick_steps_cap,
            "apply_brainiac_strategy": self.apply_brainiac_strategy,
            "notes": list(self.notes),
        }


def resolve_brainiac_live_auto_policy(
    deposit_usd: float,
    *,
    pool: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
) -> BrainiacLiveAutoPolicy:
    """SUPER-BRAINIAC execution policy: 80% skew grid; fund non-pay from SOL when wallet is short."""

    dep = max(0.01, float(deposit_usd))
    s = dict(settings or {})
    notes: list[str] = []

    fund_frac = float(
        s.get("brainiac_fund_non_pay_fraction")
        or (LIVE_AUTO_FUND_FRACTION_SMALL if dep < 3.0 else LIVE_AUTO_FUND_FRACTION_DEFAULT)
    )
    if dep < 3.0:
        notes.append(f"deposit ${dep:.2f}: fund fraction capped at {fund_frac:.2f} (keeps pay leg for open tx).")

    target_fund_usd = dep * fund_frac
    skip_fund = bool(s.get("brainiac_auto_skip_fund_swap", False))
    sol_px = float(s.get("lp_pay_funding_sol_price_usd") or 180) or 180.0
    if pool:
        from raydium_lp1.lp_junk_to_pay import non_pay_wallet_inventory_usd

        inv = non_pay_wallet_inventory_usd(pool, None, sol_price_usd=sol_px)
        have = float(inv.get("usd") or 0)
        sym = inv.get("symbol") or "non-pay"
        if have >= target_fund_usd * NON_PAY_WALLET_COVERAGE_RATIO:
            skip_fund = True
            notes.append(
                f"wallet holds ~${have:.2f} {sym} (>= {NON_PAY_WALLET_COVERAGE_RATIO:.0%} of "
                f"${target_fund_usd:.2f} target) — skip fund swap."
            )
        else:
            skip_fund = False
            notes.append(
                f"wallet short on {sym} (~${have:.2f} < ${target_fund_usd:.2f} need) — "
                "will swap pay-type/SOL -> non-pay before two-sided open."
            )
    elif not skip_fund:
        notes.append(
            f"will fund ~${target_fund_usd:.2f} non-pay from pay-type/SOL when pool is known."
        )

    min_ir = float(s.get("brainiac_min_in_range_factor", LIVE_AUTO_MIN_IN_RANGE_FACTOR))
    steps_cap = 32
    if dep < 2.0:
        steps_cap = 18
        notes.append("deposit < $2: cap band_tick_steps to reduce rent/probe cost.")
    elif dep < 3.0:
        steps_cap = 24

    if pool:
        bp = brainiac_optimal_wide_placement(
            pool,
            settings=settings,
            width_pct=LIVE_AUTO_WIDE_WIDTH_PCT,
        )
        ir = float(bp.get("in_range_factor_at_skew") or 0)
        if ir < min_ir:
            notes.append(
                f"in_range_factor {ir:.2f} < min {min_ir:.2f} — LIVE blocked unless min_in_range_factor=0."
            )

    return BrainiacLiveAutoPolicy(
        fund_non_pay_fraction=fund_frac,
        skip_fund_swap=skip_fund,
        skip_settle_after=False,
        reset_fee_session=bool(s.get("brainiac_reset_fee_session_default", False)),
        run_pretrade=True,
        min_in_range_factor=min_ir,
        pre_live_consensus_scans=int(s.get("brainiac_pre_live_consensus_scans", 5)),
        pre_live_scan_delay_sec=float(s.get("brainiac_pre_live_scan_delay_sec", 2.0)),
        wide_width_pct=LIVE_AUTO_WIDE_WIDTH_PCT,
        band_tick_steps_cap=steps_cap,
        apply_brainiac_strategy=True,
        notes=notes + [
            f"pre-LIVE consensus: {int(s.get('brainiac_pre_live_consensus_scans', 5))} refreshes "
            f"({float(s.get('brainiac_pre_live_scan_delay_sec', 2.0)):.0f}s apart) before sign."
        ],
    )


def skew_grid_search_steps() -> int:
    """Steps from -1..+1 skew; 41 points matches production rebalance."""

    return 41


def ticks_from_skew(width_pct: float, skew: float) -> tuple[float, float]:
    """Map skew in [-1,1] to below/above spot percent (total width = width_pct)."""

    sk = max(-1.0, min(1.0, float(skew)))
    w = float(width_pct)
    down_share = 0.5 - 0.25 * sk
    return w * down_share, w * (1.0 - down_share)


def optimal_skew_for_pool(
    pool: Mapping[str, Any],
    *,
    width_pct: float = WIDE_WIDTH_PCT,
    seed_skew: float = 0.0,
) -> tuple[float, float, list[dict[str, Any]]]:
    """Grid-search skew for max in_range_factor; returns (skew, ir, sample candidates)."""

    from raydium_lp1.super_brainiac.possibilities import in_range_factor

    best_skew = float(seed_skew)
    best_ir = -1.0
    skew_candidates: list[dict[str, Any]] = []
    half = (skew_grid_search_steps() - 1) // 2
    for i in range(-half, half + 1):
        sk = i / max(1, half)
        ir = in_range_factor(pool, width_pct=width_pct, placement="centered", skew=sk)
        skew_candidates.append({"skew": round(sk, 3), "in_range_factor": round(ir, 4)})
        if ir > best_ir:
            best_ir = ir
            best_skew = sk
    return best_skew, best_ir, skew_candidates


def _fee_model_leader_rankings(
    pool: Mapping[str, Any],
    *,
    settings: Mapping[str, Any] | None,
    scanner: Any | None,
) -> list[dict[str, Any]]:
    """Score all strategies except this order type (avoids recursion)."""

    from raydium_lp1.lp_order_strategies import ALL_STRATEGY_IDS
    from raydium_lp1.lp_order_strategies import (
        STRATEGY_BRAINIAC_CURSOR_SUCCESS as _SKIP_BRAINIAC_SCORE,
    )
    from raydium_lp1.scanner import ScannerConfig
    from raydium_lp1.settings_io import load_settings_json
    from raydium_lp1.super_brainiac.possibilities import BrainiacConfig, score_strategy_for_pool

    settings_path = REPO / "config" / "settings.json"
    raw = dict(settings or load_settings_json(settings_path))
    sc = scanner if scanner is not None else ScannerConfig.from_file(settings_path)
    bcfg = BrainiacConfig.from_mapping(raw, scanner=sc)
    sids = [s for s in ALL_STRATEGY_IDS if s != _SKIP_BRAINIAC_SCORE]
    rankings = [score_strategy_for_pool(pool, sid, cfg=bcfg, scanner=sc) for sid in sids]
    rankings.sort(key=lambda s: -float(s.get("brainiac_score") or 0))
    return rankings


def brainiac_optimal_wide_placement(
    pool: Mapping[str, Any],
    *,
    settings: Mapping[str, Any] | None = None,
    scanner: Any | None = None,
    width_pct: float = WIDE_WIDTH_PCT,
) -> dict[str, Any]:
    """Pick skew for fixed 80% width maximizing 24h price overlap; attach fee-model context."""

    from raydium_lp1.lp_range_planner import asymmetric_quote_band, spot_price_quote_per_base

    rankings = _fee_model_leader_rankings(pool, settings=settings, scanner=scanner)
    leader = rankings[0] if rankings else {}
    leader_skew = float(leader.get("skew") or 0.0)

    spot, spot_src = spot_price_quote_per_base(pool)
    if spot is None:
        spot = float(pool.get("price") or 78642.0)

    best_skew, best_ir, skew_candidates = optimal_skew_for_pool(
        pool, width_pct=width_pct, seed_skew=leader_skew
    )

    tick_lo, tick_hi = ticks_from_skew(width_pct, best_skew)
    lo_p, hi_p = asymmetric_quote_band(float(spot), width_pct, best_skew)

    return {
        "strategy_id": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        "official_name": STRATEGY_OFFICIAL_NAME,
        "synopsis": SYNOPSIS,
        "fee_model_leader": {
            "strategy_id": leader.get("strategy_id"),
            "brainiac_score": leader.get("brainiac_score"),
            "theoretical_apr_pct": leader.get("theoretical_apr_pct"),
            "placement": leader.get("placement"),
            "leader_skew": leader_skew,
        },
        "strategy_rankings_top6": rankings[:6],
        "wide_width_pct": width_pct,
        "optimal_skew": round(best_skew, 3),
        "in_range_factor_at_skew": round(best_ir, 4),
        "tick_lower_pct_below": round(tick_lo, 3),
        "tick_upper_pct_above": round(tick_hi, 3),
        "spot_source": spot_src,
        "quote_band_quote_per_base": {
            "lower": round(lo_p, 8),
            "upper": round(hi_p, 8),
            "spot": round(float(spot), 8),
        },
        "placement_label": (
            f"80% wide straddle skewed (below {tick_lo:.1f}% / above {tick_hi:.1f}% of spot)"
        ),
        "skew_candidates_sample": skew_candidates[::8],
        "rent_model": "raydium_no_sunk_tick_arrays",
    }


def build_brainiac_cursor_open_plan(
    pool: Mapping[str, Any],
    momentum: Mapping[str, Any] | None,
    *,
    default_width_pct: float = WIDE_WIDTH_PCT,
    skew_use_momentum: bool = True,
    settings: Mapping[str, Any] | None = None,
    scanner: Any | None = None,
) -> dict[str, Any]:
    """Strategy plan dict compatible with ``build_open_order`` consumers."""

    placement = brainiac_optimal_wide_placement(
        pool,
        settings=settings,
        scanner=scanner,
        width_pct=min(WIDE_WIDTH_PCT, max(10.0, float(default_width_pct))),
    )
    tick_lo = float(placement["tick_lower_pct_below"])
    tick_hi = float(placement["tick_upper_pct_above"])
    spot_band = placement.get("quote_band_quote_per_base") or {}

    return {
        "strategy_id": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        "strategy_name": STRATEGY_OFFICIAL_NAME,
        "strategy_description": SYNOPSIS,
        "width_pct": WIDE_WIDTH_PCT,
        "width_note": "brainiac_80_skew_grid",
        "skew": placement["optimal_skew"],
        "skew_notes": [
            f"grid_search ir={placement['in_range_factor_at_skew']}",
            f"leader={placement.get('fee_model_leader', {}).get('strategy_id')}",
        ],
        "tick_lower_pct_below": tick_lo,
        "tick_upper_pct_above": tick_hi,
        "band": {
            "lower_quote_per_base": spot_band.get("lower"),
            "upper_quote_per_base": spot_band.get("upper"),
            "spot_quote_per_base": spot_band.get("spot"),
            "placement": PLACEMENT_BRAINIAC_SKEWED_WIDE,
        },
        "brainiac_placement": placement,
        "execution": "live_ready",
        "live_hook": "raydium_lp1.lp_brainiac_cursor_success.open_clmm_with_brainiac_cursor_success",
        "reasoning": {
            "placement": list(PLACEMENT_REASONING),
            "settlement": list(SETTLEMENT_REASONING),
        },
        "settlement_policy": settlement_policy_for_plan(pool, scanner),
        "open_requirements": {
            "force_pay_token_only": False,
            "wallet_inventory_full_range": True,
            "wide_range": False,
            "spend_less_auto_fallback_from_wide": False,
            "lp_rent_conservative_estimates": False,
            "lp_sweep_junk_to_pay_leg": True,
            "fund_non_pay_from_pay_mint_only": True,
        },
    }


def settlement_policy_for_plan(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    from raydium_lp1.lp_junk_to_pay import settlement_policy_for_pool

    return {
        "module": SETTLEMENT_MODULE,
        "reasoning": list(SETTLEMENT_REASONING),
        **settlement_policy_for_pool(pool, config),
    }


def apply_brainiac_fee_and_settlement_settings(
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge fee-guard + pay-type settlement flags for this order type."""

    s = fee_settings_for_brainiac_procedure(base)
    s["lp_sweep_junk_to_pay_leg"] = True
    return s


def settle_wallet_after_brainiac_trade(
    pool: Mapping[str, Any],
    config: Any | None = None,
    *,
    sol_price_usd: float | None = None,
    fee_settings: dict[str, Any] | None = None,
    sweep_junk: bool = True,
) -> dict[str, Any]:
    """Post-trade hygiene using pay-type settlement rules for this order type."""

    from raydium_lp1.lp_junk_to_pay import keep_mints_for_pool
    from raydium_lp1.lp_wallet_settlement import settle_wallet_after_trade

    settings = apply_brainiac_fee_and_settlement_settings(fee_settings)
    return settle_wallet_after_trade(
        pool=pool,
        config=config,
        sol_price_usd=sol_price_usd,
        fee_settings=settings,
        keep_mints=keep_mints_for_pool(pool, config),
        sweep_junk=sweep_junk,
    )


def fund_non_pay_leg_if_needed(
    pool: Mapping[str, Any],
    *,
    target_non_pay_usd: float,
    config: Any | None = None,
    sol_price_usd: float = 180.0,
    user_skip_fund_swap: bool = False,
) -> dict[str, Any]:
    """Ensure non-pay inventory for two-sided open; fund from SOL/USDC when wallet is short."""

    return ensure_non_pay_leg_for_two_sided_open(
        pool,
        target_non_pay_usd=target_non_pay_usd,
        config=config,
        sol_price_usd=sol_price_usd,
        user_skip_fund_swap=user_skip_fund_swap,
    )


def ensure_non_pay_leg_for_two_sided_open(
    pool: Mapping[str, Any],
    *,
    target_non_pay_usd: float,
    config: Any | None = None,
    sol_price_usd: float = 180.0,
    user_skip_fund_swap: bool = False,
    min_fund_usd: float = 0.25,
) -> dict[str, Any]:
    """Two-sided wallet_inventory requires non-pay token — acquire from pay-type/SOL if missing."""

    from raydium_lp1.lp_junk_to_pay import fund_non_pay_leg_from_pay_mint, non_pay_wallet_inventory_usd

    target = max(0.0, float(target_non_pay_usd))
    inv = non_pay_wallet_inventory_usd(pool, config, sol_price_usd=sol_price_usd)
    have = float(inv.get("usd") or 0)
    sym = str(inv.get("symbol") or "non-pay")
    enough = have >= target * NON_PAY_WALLET_COVERAGE_RATIO if target > 0 else True

    if enough:
        return {
            "ok": True,
            "skipped": True,
            "reason": "wallet_has_non_pay",
            "non_pay_symbol": sym,
            "have_usd": have,
            "target_usd": round(target, 4),
        }

    shortfall = max(0.0, target - have)
    fund_usd = max(float(min_fund_usd), shortfall, target * 0.5)
    overridden_skip = bool(user_skip_fund_swap)
    sw = fund_non_pay_leg_from_pay_mint(
        pool,
        target_non_pay_usd=fund_usd,
        sol_price_usd=sol_price_usd,
        config=config,
    )
    return {
        **sw,
        "skipped": False,
        "forced_fund_despite_skip_flag": overridden_skip,
        "non_pay_symbol": sym,
        "have_usd_before": have,
        "target_usd": round(target, 4),
        "funded_usd_attempt": round(fund_usd, 4),
        "note": (
            f"Acquired {sym} from pay-type/SOL for two-sided open "
            f"(had ~${have:.2f}, need ~${target:.2f})."
        ),
    }


def open_kwargs_from_plan(
    plan: Mapping[str, Any],
    *,
    deposit_usd: float | None = None,
    band_tick_steps_cap: int | None = None,
) -> dict[str, Any]:
    """CLMM ``open_position`` kwargs for this order type."""

    w = float(plan.get("width_pct") or WIDE_WIDTH_PCT)
    steps = int(max(10, min(32, round(6 + w * 0.45))))
    if band_tick_steps_cap is not None:
        steps = min(steps, int(band_tick_steps_cap))
    if deposit_usd is not None and float(deposit_usd) < 2.0:
        steps = min(steps, 18)
    return {
        "single_side": None,
        "wide_range": False,
        "full_range": False,
        "literal_pool_full_range": False,
        "tick_lower_pct_below": float(
            plan.get("tick_lower_pct_below")
            or (plan.get("brainiac_placement") or {}).get("tick_lower_pct_below")
            or 40.0
        ),
        "tick_upper_pct_above": float(
            plan.get("tick_upper_pct_above")
            or (plan.get("brainiac_placement") or {}).get("tick_upper_pct_above")
            or 40.0
        ),
        "band_tick_steps": steps,
        "pay_mint_only": False,
        "wallet_inventory_full_range": True,
        "wallet_inventory_wide_range": True,
        "slippage_bps": 2500,
    }


def fee_settings_for_brainiac_procedure(base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Fee guard + SPEND LESS knobs used on the successful rebalance."""

    from raydium_lp1.settings_io import load_settings_json

    s = dict(base or load_settings_json(REPO / "config" / "settings.json"))
    s["fee_guard_enabled"] = True
    s["lp_rent_conservative_estimates"] = False
    s["max_session_tx_attempts"] = max(24, int(s.get("max_session_tx_attempts") or 5))
    s["max_session_spend_sol"] = max(0.4, float(s.get("max_session_spend_sol") or 0.12))
    s["max_rent_escrow_pct_of_deposit"] = max(15.0, float(s.get("max_rent_escrow_pct_of_deposit") or 10))
    s["spend_less_auto_fallback_from_wide"] = False
    s["spend_less_on_chain_rent_buffer_sol"] = min(
        0.02, float(s.get("spend_less_on_chain_rent_buffer_sol") or 0.05)
    )
    s["lp_sweep_junk_to_pay_leg"] = True
    return s


def open_clmm_with_brainiac_cursor_success(
    *,
    pool_id: str,
    input_amount_usd: float,
    pool: Mapping[str, Any] | None = None,
    fee_guard_settings: dict[str, Any] | None = None,
    sol_price_usd: float | None = None,
    auto_tune: bool = True,
    skip_fund_swap: bool | None = None,
    reset_fee_session: bool | None = None,
    skip_settle_after: bool | None = None,
    wide_width_pct: float | None = None,
    placement_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """LIVE CLMM open: 80% skew grid placement via ``open_clmm_candidate`` (no wizard runner recursion)."""

    from raydium_lp1.fee_guard import reset_session_ledger
    from raydium_lp1.live_executor import open_clmm_candidate
    from raydium_lp1.lp_order_strategies import STRATEGY_BRAINIAC_CURSOR_SUCCESS
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    load_dotenv()
    settings = apply_brainiac_fee_and_settlement_settings(fee_guard_settings)
    sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
    pool_row = pool if pool is not None else fetch_pool_by_id(pool_id.strip(), config=sc)

    auto = (
        resolve_brainiac_live_auto_policy(input_amount_usd, pool=pool_row, settings=settings)
        if auto_tune
        else BrainiacLiveAutoPolicy(
            wide_width_pct=float(wide_width_pct or LIVE_AUTO_WIDE_WIDTH_PCT),
            skip_fund_swap=bool(skip_fund_swap) if skip_fund_swap is not None else False,
            skip_settle_after=bool(skip_settle_after) if skip_settle_after is not None else False,
            reset_fee_session=False,
            run_pretrade=False,
        )
    )
    if skip_fund_swap is not None:
        auto.skip_fund_swap = bool(skip_fund_swap)
    if reset_fee_session is not None and auto.reset_fee_session:
        reset_session_ledger()
    if skip_settle_after is not None:
        auto.skip_settle_after = bool(skip_settle_after)

    plan = (
        dict(placement_plan)
        if placement_plan is not None
        else build_brainiac_cursor_open_plan(
            pool_row,
            pool_row.get("momentum"),
            default_width_pct=auto.wide_width_pct,
            settings=settings,
            scanner=sc,
        )
    )
    out = open_clmm_candidate(
        pool_id=pool_id.strip(),
        input_amount_usd=float(input_amount_usd),
        wallet_inventory_full_range=True,
        tick_lower_pct_below=float(plan.get("tick_lower_pct_below") or 40.0),
        tick_upper_pct_above=float(plan.get("tick_upper_pct_above") or 40.0),
        force_pay_token_only=False,
        strategy_id=STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        fee_guard_settings=settings,
        sol_price_usd=sol_price_usd,
        open_deposit_usd=float(input_amount_usd),
        band_tick_steps_cap=auto.band_tick_steps_cap,
        skip_wallet_settlement=auto.skip_settle_after,
    )
    out["brainiac_auto_policy"] = auto.to_dict()
    out.setdefault("settlement_policy", plan.get("settlement_policy"))
    out.setdefault("reasoning", plan.get("reasoning"))
    out["placement_plan"] = {
        "skew": plan.get("skew"),
        "tick_lower_pct_below": plan.get("tick_lower_pct_below"),
        "tick_upper_pct_above": plan.get("tick_upper_pct_above"),
        "brainiac_placement": plan.get("brainiac_placement"),
    }
    return out


@dataclass
class RebalanceCostLedger:
    """USD-aware procedure ledger (closes + opens + swaps)."""

    pool_id: str
    started_at: str = ""
    sol_price_usd: float = 180.0
    idle_per_sol: float = 78642.0
    snaps: dict[str, dict[str, float]] = field(default_factory=dict)
    brainiac: dict[str, Any] = field(default_factory=dict)
    closes: list[dict[str, Any]] = field(default_factory=list)
    opens: list[dict[str, Any]] = field(default_factory=list)
    funding_swaps: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def wallet_usd(self, snap: Mapping[str, float]) -> float:
        sol = float(snap.get("sol") or 0)
        usdc = float(snap.get("usdc") or 0)
        idle_h = float(snap.get("idle_human") or 0)
        idle_usd = (idle_h / max(1.0, self.idle_per_sol)) * self.sol_price_usd
        return sol * self.sol_price_usd + usdc + idle_usd

    def finalize(self) -> dict[str, Any]:
        start = self.snaps.get("start") or {}
        end = self.snaps.get("end") or {}
        close_fees = sum(float(c.get("network_fee_sol") or 0) for c in self.closes)
        open_fees = sum(float(o.get("network_fee_sol") or 0) for o in self.opens)
        swap_fees = sum(float(s.get("network_fee_sol") or 0) for s in self.funding_swaps)
        total_fee_sol = close_fees + open_fees + swap_fees
        return {
            "order_type": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
            "official_name": STRATEGY_OFFICIAL_NAME,
            "pool_id": self.pool_id,
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "sol_price_usd": self.sol_price_usd,
            "brainiac_placement": self.brainiac,
            "wallet_start": start,
            "wallet_end": end,
            "wallet_usd_start": round(self.wallet_usd(start), 2),
            "wallet_usd_end": round(self.wallet_usd(end), 2),
            "wallet_usd_delta": round(self.wallet_usd(end) - self.wallet_usd(start), 2),
            "permanent_loss_usd": {
                "network_fees_only": round(total_fee_sol * self.sol_price_usd, 4),
                "breakdown": {
                    "closes_usd": round(close_fees * self.sol_price_usd, 4),
                    "opens_usd": round(open_fees * self.sol_price_usd, 4),
                    "funding_swaps_usd": round(swap_fees * self.sol_price_usd, 4),
                },
                "note": (
                    "Permanent = network fees only. LP deposits + ~0.008 SOL/NFT rent are recoverable on close."
                ),
            },
            "closes": self.closes,
            "opens": self.opens,
            "funding_swaps": self.funding_swaps,
            "notes": self.notes,
        }
