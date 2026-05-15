"""Shadow exit / PnL modeling for dry-run dashboards (not realized on-chain).

``build_shadow_activity_for_pool`` uses the same Jupiter/Raydium **probe** quotes
already stored under ``pool["sellability"]``. It converts quoted WSOL ``outAmount``
(from the winning route's ``best_price`` field) into **gross SOL** for each leg,
then builds a deliberately conservative **floor** ``min(leg_a, leg_b)`` so both
hypothetical token clips could clear at the quoted prices.

**NET model:** ``pnl_sol_net_model = exit_modeled_gross_sol_floor - entry_assumption_sol
- priority_fee_reserve_sol``.

This is **not** net of Raydium pool fee tiers, impermanent loss, or exact swap
execution gas beyond ``priority_fee_reserve_sol``. Treat it as a **screening
signal**, not accounting-grade PnL. Real green money requires fills + ledgering.
"""

from __future__ import annotations

from typing import Any

from raydium_lp1 import trade_activity

LAMPORTS_PER_SOL = 1_000_000_000.0


def _gross_sol_from_route_check(route: dict[str, Any]) -> float | None:
    """Return gross SOL implied by a RouteCheck dict when the route targets SOL/WSOL."""

    sym = str(route.get("target_symbol") or "").upper()
    if sym not in ("SOL", "WSOL"):
        return None
    bp = route.get("best_price")
    if bp is None:
        return None
    try:
        lamports = float(bp)
    except (TypeError, ValueError):
        return None
    return lamports / LAMPORTS_PER_SOL


def build_shadow_activity_for_pool(
    pool: dict[str, Any],
    *,
    entry_assumption_sol: float,
    priority_fee_reserve_sol: float,
) -> dict[str, Any]:
    """Return a JSON-serializable shadow exit / PnL panel for one pool."""

    sell = pool.get("sellability")
    pair = f"{pool.get('mint_a_symbol', '')}/{pool.get('mint_b_symbol', '')}"
    base: dict[str, Any] = {
        "pair": pair,
        "pool_id": pool.get("id"),
        "entry_assumption_sol": float(entry_assumption_sol),
        "priority_fee_reserve_sol": float(priority_fee_reserve_sol),
        "exit_probe_gross_sol_per_leg": {"token_a": None, "token_b": None},
        "exit_modeled_gross_sol_floor": None,
        "pnl_sol_net_model": None,
        "open_close_phase": "shadow_watch_only",
        "methodology": (
            "MODEL: probe ExactIn quotes at fixed token amounts (see routes.DEFAULT_PROBE_AMOUNT); "
            "gross SOL = WSOL outAmount / 1e9. Floor = min(legs) is a conservative fiction for "
            "two-sided inventory, not remove-liquidity math. NET subtracts priority_fee_reserve_sol "
            "only — add pool fees, IL, and actual priority fees for production."
        ),
    }
    base["would_open_lp"] = trade_activity.describe_open_lp_dry_run(
        pool, notion_sol=float(entry_assumption_sol)
    )
    base["would_close_lp"] = trade_activity.describe_close_lp_dry_run(pool)
    if not isinstance(sell, dict) or not sell.get("ok"):
        base["status"] = "no_sellability_or_not_ok"
        return base

    ta = sell.get("token_a") if isinstance(sell.get("token_a"), dict) else {}
    tb = sell.get("token_b") if isinstance(sell.get("token_b"), dict) else {}
    ga = _gross_sol_from_route_check(ta)
    gb = _gross_sol_from_route_check(tb)
    base["exit_probe_gross_sol_per_leg"] = {"token_a": ga, "token_b": gb}

    gross_floor: float | None = None
    if ga is not None and gb is not None:
        gross_floor = min(ga, gb)
    elif ga is not None:
        gross_floor = ga
    elif gb is not None:
        gross_floor = gb

    base["exit_modeled_gross_sol_floor"] = gross_floor
    if gross_floor is not None:
        base["pnl_sol_net_model"] = gross_floor - float(entry_assumption_sol) - float(priority_fee_reserve_sol)
        base["status"] = "modeled"
    else:
        base["status"] = "no_sol_quoted_route"
    return base
