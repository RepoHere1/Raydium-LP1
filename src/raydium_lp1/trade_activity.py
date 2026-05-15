"""Trading activity scaffolding (dry-run only).

These helpers describe what **would** happen for open / close / swap-back
without signing. Real execution must wait for audited live paths and an
explicit operator gate.
"""

from __future__ import annotations

from typing import Any


def describe_open_lp_dry_run(pool: dict[str, Any], *, notion_sol: float) -> dict[str, Any]:
    """Return a JSON-serializable record for a hypothetical LP add."""

    return {
        "phase": "would_open_lp",
        "dry_run": True,
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol', '')}/{pool.get('mint_b_symbol', '')}",
        "notional_sol_assumption": float(notion_sol),
        "note": "DRY-RUN: no Raydium add-liquidity instruction built or signed.",
    }


def describe_close_lp_dry_run(pool: dict[str, Any], *, base_symbol: str = "SOL") -> dict[str, Any]:
    """Return a JSON-serializable record for a hypothetical remove-liquidity + exit."""

    return {
        "phase": "would_close_lp",
        "dry_run": True,
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol', '')}/{pool.get('mint_b_symbol', '')}",
        "swap_back_to": base_symbol.upper(),
        "note": "DRY-RUN: use emergency swap plans + Jupiter v6 swap endpoint when live code exists.",
    }


def describe_swap_to_sol_dry_run(pool: dict[str, Any], *, token_side: str) -> dict[str, Any]:
    """``token_side`` is ``\"a\"`` or ``\"b\"`` — which leg to model exiting first."""

    side = (token_side or "b").lower()
    mint = pool.get("mint_a" if side == "a" else "mint_b", "")
    sym = pool.get("mint_a_symbol" if side == "a" else "mint_b_symbol", "")
    return {
        "phase": "would_swap_to_sol",
        "dry_run": True,
        "pool_id": pool.get("id"),
        "token_mint": mint,
        "token_symbol": sym,
        "note": "DRY-RUN: route via routes.check_sell_route / emergency.build_swap_plan; no signature.",
    }
