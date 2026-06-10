"""Route every LP order type to the correct LIVE open executor.

All dashboard, wizard, Super Brainiac, and CLI entry points should call
``execute_strategy_live_open`` so each strategy uses its intended on-chain path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from raydium_lp1.lp_order_strategies import (
    STRATEGY_BRAINIAC_CURSOR_SUCCESS,
    get_strategy,
)
from raydium_lp1.strategy_registry import resolve_lp_order_strategy_id

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LATEST = REPO / "reports" / "latest.json"


def is_brainiac_strategy(strategy_id: str | None) -> bool:
    return (strategy_id or "").strip() == STRATEGY_BRAINIAC_CURSOR_SUCCESS


def resolve_strategy_id(
    strategy_id: str | None = None,
    *,
    settings: Mapping[str, Any] | None = None,
    config: Any | None = None,
) -> str:
    if strategy_id and str(strategy_id).strip():
        return str(strategy_id).strip()
    if settings:
        sid = str(settings.get("lp_active_strategy") or "").strip()
        if sid:
            return sid
    if config is not None:
        sid = str(getattr(config, "lp_active_strategy", "") or "").strip()
        if sid:
            return sid
    return "auto_volatility_pick"


def live_hook_for_strategy(strategy_id: str) -> str:
    """Return the documented LIVE hook for a strategy id."""

    if is_brainiac_strategy(strategy_id):
        return "raydium_lp1.lp_brainiac_cursor_success.open_clmm_with_brainiac_cursor_success"
    if get_strategy(strategy_id):
        return "raydium_lp1.live_executor.open_clmm_candidate"
    return "raydium_lp1.live_executor.open_clmm_candidate"


def execute_strategy_live_open(
    *,
    pool_id: str | None = None,
    deposit_usd: float | None = None,
    input_amount_sol: float | None = None,
    strategy_id: str | None = None,
    force_pay_token_only: bool | None = None,
    fee_guard_settings: dict[str, Any] | None = None,
    sol_price_usd: float | None = None,
    brainiac_full_procedure: bool = False,
    placement_plan: Mapping[str, Any] | None = None,
    skip_fund_swap: bool | None = None,
    reset_fee_session: bool = False,
    skip_wallet_settlement: bool = False,
    tick_lower_pct_below: float | None = None,
    tick_upper_pct_above: float | None = None,
    band_tick_steps_cap: int | None = None,
    wallet_inventory_full_range: bool | None = None,
    latest_path: Path = DEFAULT_LATEST,
    open_deposit_usd: float | None = None,
) -> dict[str, Any]:
    """Single LIVE open gate — dispatches by strategy to the correct executor."""

    sid = resolve_lp_order_strategy_id(
        resolve_strategy_id(strategy_id, settings=fee_guard_settings)
    )

    if brainiac_full_procedure:
        if not pool_id or not str(pool_id).strip():
            return {"ok": False, "error": "pool_id required for brainiac_full_procedure"}
        from raydium_lp1.brainiac_open_runner import BrainiacOpenRequest, execute_brainiac_open

        dep = float(deposit_usd if deposit_usd is not None else open_deposit_usd or 0.25)
        req = BrainiacOpenRequest(
            pool_id=str(pool_id).strip(),
            deposit_usd=dep,
            sol_price_usd=sol_price_usd,
            reset_fee_session=bool(reset_fee_session),
            skip_fund_swap=bool(skip_fund_swap) if skip_fund_swap is not None else False,
            skip_settle_after=bool(skip_wallet_settlement),
        )
        out = execute_brainiac_open(req)
        out["live_router"] = {
            "strategy_id": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
            "path": "brainiac_open_runner.execute_brainiac_open",
        }
        return out

    if is_brainiac_strategy(sid):
        dep = float(deposit_usd if deposit_usd is not None else open_deposit_usd or 0.25)
        if pool_id and str(pool_id).strip():
            from raydium_lp1.lp_brainiac_cursor_success import open_clmm_with_brainiac_cursor_success
            from raydium_lp1.lp_selection import fetch_pool_by_id
            from raydium_lp1.scanner import ScannerConfig, load_dotenv

            load_dotenv()
            sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
            pool_row = fetch_pool_by_id(str(pool_id).strip(), config=sc)
            out = open_clmm_with_brainiac_cursor_success(
                pool_id=str(pool_id).strip(),
                input_amount_usd=dep,
                pool=pool_row,
                fee_guard_settings=fee_guard_settings,
                sol_price_usd=sol_price_usd,
                auto_tune=True,
                skip_fund_swap=skip_fund_swap,
                reset_fee_session=reset_fee_session,
                skip_settle_after=skip_wallet_settlement,
                placement_plan=dict(placement_plan) if placement_plan else None,
            )
            out["live_router"] = {
                "strategy_id": sid,
                "path": "lp_brainiac_cursor_success.open_clmm_with_brainiac_cursor_success",
            }
            return out
        # No explicit pool — top-candidate path via live_executor (auto micro pay-only).
        from raydium_lp1.live_executor import open_clmm_candidate

        out = open_clmm_candidate(
            pool_id=None,
            latest_path=latest_path,
            input_amount_sol=input_amount_sol,
            input_amount_usd=dep,
            strategy_id=sid,
            fee_guard_settings=fee_guard_settings,
            sol_price_usd=sol_price_usd,
            open_deposit_usd=dep,
            band_tick_steps_cap=band_tick_steps_cap,
            skip_wallet_settlement=skip_wallet_settlement,
        )
        out["live_router"] = {
            "strategy_id": sid,
            "path": "live_executor.open_clmm_candidate",
            "note": "brainiac top-candidate (no explicit pool_id)",
        }
        return out

    from raydium_lp1.live_executor import open_clmm_candidate

    kw: dict[str, Any] = {
        "pool_id": pool_id,
        "latest_path": latest_path,
        "input_amount_sol": input_amount_sol,
        "input_amount_usd": deposit_usd,
        "force_pay_token_only": force_pay_token_only,
        "strategy_id": sid,
        "fee_guard_settings": fee_guard_settings,
        "sol_price_usd": sol_price_usd,
        "open_deposit_usd": open_deposit_usd if open_deposit_usd is not None else deposit_usd,
        "band_tick_steps_cap": band_tick_steps_cap,
        "skip_wallet_settlement": skip_wallet_settlement,
    }
    if tick_lower_pct_below is not None:
        kw["tick_lower_pct_below"] = tick_lower_pct_below
    if tick_upper_pct_above is not None:
        kw["tick_upper_pct_above"] = tick_upper_pct_above
    if wallet_inventory_full_range is not None:
        kw["wallet_inventory_full_range"] = wallet_inventory_full_range

    out = open_clmm_candidate(**kw)
    out["live_router"] = {
        "strategy_id": sid,
        "path": "live_executor.open_clmm_candidate",
        "live_hook": live_hook_for_strategy(sid),
    }
    return out
