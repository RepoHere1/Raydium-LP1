"""Auto-fund USDC/USDT/USD1 pay legs via Jupiter SOL swaps before LIVE CLMM opens."""

from __future__ import annotations

import math
from typing import Any

from raydium_lp1.pay_token_catalog import (
    STABLE_PAY_SYMBOLS,
    is_stable_pay_symbol,
    pay_token_spec,
)
from raydium_lp1.routes import WSOL_MINT

LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_SOL_PRICE_USD = 180.0
DEFAULT_FUNDING_BUFFER_PCT = 0.03
DEFAULT_STABLE_DUST_HUMAN = 0.02
DEFAULT_SWAP_SLIPPAGE_BPS = 150


def pay_funding_enabled(config: Any | None) -> bool:
    if config is None:
        return True
    return bool(getattr(config, "lp_pay_funding_enabled", True))


def funding_buffer_pct(config: Any | None) -> float:
    if config is None:
        return DEFAULT_FUNDING_BUFFER_PCT
    return max(0.0, float(getattr(config, "lp_pay_funding_buffer_pct", DEFAULT_FUNDING_BUFFER_PCT)))


def stable_dust_human(config: Any | None) -> float:
    if config is None:
        return DEFAULT_STABLE_DUST_HUMAN
    return max(0.0, float(getattr(config, "lp_pay_funding_dust_usd", DEFAULT_STABLE_DUST_HUMAN)))


def swap_slippage_bps(config: Any | None) -> int:
    if config is None:
        return DEFAULT_SWAP_SLIPPAGE_BPS
    return max(10, int(getattr(config, "lp_pay_funding_slippage_bps", DEFAULT_SWAP_SLIPPAGE_BPS)))


def sol_price_usd_from_config(config: Any | None) -> float:
    if config is None:
        return DEFAULT_SOL_PRICE_USD
    v = float(getattr(config, "lp_pay_funding_sol_price_usd", 0) or 0)
    return v if v > 0 else DEFAULT_SOL_PRICE_USD


def pay_balance_human(wallet_bal: dict[str, Any], pay_symbol: str) -> float:
    spec = pay_token_spec(pay_symbol)
    if spec is None:
        return 0.0
    if spec.symbol == "SOL":
        return float(wallet_bal.get("sol_balance") or 0.0)
    return float(wallet_bal.get(spec.balance_field) or 0.0)


def compute_pay_requirement(
    deposit_human: float,
    *,
    buffer_pct: float = DEFAULT_FUNDING_BUFFER_PCT,
) -> float:
    dep = max(0.0, float(deposit_human))
    return dep * (1.0 + max(0.0, buffer_pct))


def compute_pay_shortfall(
    deposit_human: float,
    current_balance: float,
    *,
    buffer_pct: float = DEFAULT_FUNDING_BUFFER_PCT,
    dust_human: float = DEFAULT_STABLE_DUST_HUMAN,
) -> dict[str, float]:
    required = compute_pay_requirement(deposit_human, buffer_pct=buffer_pct)
    current = max(0.0, float(current_balance))
    shortfall = max(0.0, required - current)
    return {
        "required_human": required,
        "current_human": current,
        "shortfall_human": shortfall,
        "deposit_human": float(deposit_human),
        "dust_human": float(dust_human),
    }


def estimate_sol_for_stable_shortfall(
    shortfall_human: float,
    *,
    sol_price_usd: float,
    swap_buffer: float = 1.12,
) -> float:
    if shortfall_human <= 0:
        return 0.0
    px = float(sol_price_usd)
    if px <= 0:
        raise ValueError("sol_price_usd must be > 0 for pay-token funding estimate")
    return (float(shortfall_human) / px) * max(1.0, float(swap_buffer))


def refine_sol_swap_lamports_via_quote(
    target_out_raw: int,
    *,
    output_mint: str,
    slippage_bps: int = DEFAULT_SWAP_SLIPPAGE_BPS,
) -> int | None:
    """Optional Jupiter quote to size SOL in for a target stable out-amount."""

    if target_out_raw <= 0:
        return None
    from raydium_lp1 import raydium_clmm

    probe_sol = [0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5]
    best_in: int | None = None
    for sol_amt in probe_sol:
        lamports = int(sol_amt * LAMPORTS_PER_SOL)
        q = raydium_clmm.quote_sell(
            input_mint=WSOL_MINT,
            output_mint=output_mint,
            amount_raw=lamports,
            slippage_bps=slippage_bps,
            max_impact_pct=50.0,
            timeout=12.0,
        )
        if not q.get("ok") or q.get("verdict") == "no_route":
            continue
        try:
            out_raw = int(q.get("out_amount") or 0)
        except (TypeError, ValueError):
            continue
        if out_raw >= target_out_raw:
            best_in = lamports
            break
    return best_in


def plan_pay_token_funding(
    pay_symbol: str,
    pay_mint: str,
    deposit_human: float,
    wallet_bal: dict[str, Any],
    *,
    config: Any | None = None,
    sol_price_usd: float | None = None,
) -> dict[str, Any]:
    sym = (pay_symbol or "").strip().upper()
    if sym in ("SOL", "WSOL") or not is_stable_pay_symbol(sym):
        return {
            "needed": False,
            "pay_symbol": sym,
            "reason": "pay_leg_is_sol_or_not_stable",
        }

    spec = pay_token_spec(sym)
    if spec is None:
        return {"needed": False, "pay_symbol": sym, "reason": "unknown_pay_token"}

    buf = funding_buffer_pct(config)
    dust = stable_dust_human(config)
    short = compute_pay_shortfall(
        deposit_human,
        pay_balance_human(wallet_bal, sym),
        buffer_pct=buf,
        dust_human=dust,
    )
    if short["shortfall_human"] <= dust:
        return {
            "needed": False,
            "pay_symbol": sym,
            "pay_mint": pay_mint,
            "already_sufficient": True,
            **short,
        }

    px = float(sol_price_usd if sol_price_usd and sol_price_usd > 0 else sol_price_usd_from_config(config))
    est_sol = estimate_sol_for_stable_shortfall(short["shortfall_human"], sol_price_usd=px)
    target_out_raw = int(math.ceil(short["shortfall_human"] * (10 ** spec.decimals)))
    lamports = refine_sol_swap_lamports_via_quote(
        target_out_raw,
        output_mint=pay_mint,
        slippage_bps=swap_slippage_bps(config),
    )
    if lamports is None:
        lamports = int(math.ceil(est_sol * LAMPORTS_PER_SOL))
    else:
        lamports = int(math.ceil(lamports * 1.05))

    sol_avail = float(wallet_bal.get("sol_balance") or 0.0)
    return {
        "needed": True,
        "pay_symbol": sym,
        "pay_mint": pay_mint,
        "sol_price_usd": px,
        "estimated_sol_swap": lamports / LAMPORTS_PER_SOL,
        "amount_lamports": lamports,
        "target_out_raw": target_out_raw,
        "sol_balance": sol_avail,
        **short,
    }


def ensure_pay_token_for_open(
    pay_res: Any,
    deposit_human: float,
    *,
    config: Any | None = None,
    fee_settings: dict[str, Any] | None = None,
    reserve_sol: float = 0.02,
    open_cost_sol: float = 0.042,
    sol_price_usd: float | None = None,
) -> dict[str, Any]:
    """Swap SOL → pay stable when balance is below LP deposit need. No-op for SOL pay leg."""

    if not pay_funding_enabled(config):
        return {"ok": True, "skipped": True, "reason": "funding_disabled"}

    sym = str(getattr(pay_res, "pay_symbol", "") or "").upper()
    if sym in ("SOL", "WSOL") or sym not in STABLE_PAY_SYMBOLS:
        return {"ok": True, "skipped": True, "reason": "pay_leg_is_sol", "pay_symbol": sym}

    from raydium_lp1 import raydium_clmm
    from raydium_lp1.fee_guard import assert_swap_allowed
    from raydium_lp1.live_guard import guard_onchain

    bal = raydium_clmm.wallet_balance(timeout=25.0)
    if not bal.get("ok"):
        return {"ok": False, "error": bal.get("error") or "wallet_balance failed", "stage": "balance"}

    plan = plan_pay_token_funding(
        sym,
        str(pay_res.pay_mint),
        deposit_human,
        bal,
        config=config,
        sol_price_usd=sol_price_usd,
    )
    if not plan.get("needed"):
        return {"ok": True, "skipped": True, "funding_plan": plan}

    lamports = int(plan.get("amount_lamports") or 0)
    est_sol = lamports / LAMPORTS_PER_SOL
    min_sol_left = float(reserve_sol) + float(open_cost_sol) + 0.003
    sol_after = float(bal.get("sol_balance") or 0.0) - est_sol
    if sol_after < min_sol_left:
        return {
            "ok": False,
            "error": (
                f"insufficient SOL to fund {sym}: need ~{est_sol:.4f} SOL swap + "
                f"~{min_sol_left:.4f} SOL reserved for rent/fees; balance={bal.get('sol_balance'):.4f}"
            ),
            "funding_plan": plan,
            "stage": "precheck",
        }

    try:
        assert_swap_allowed(est_sol, settings=fee_settings)
        guard_onchain(
            f"swap SOL for {sym}",
            script_name="swap_sol_to_pay.mjs",
            deposit_sol=est_sol,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "funding_plan": plan, "stage": "guard"}

    swap = raydium_clmm.swap_sol_for_pay_token(
        output_mint=str(pay_res.pay_mint),
        amount_lamports=lamports,
        slippage_bps=swap_slippage_bps(config),
        timeout=90.0,
    )
    if not swap.get("ok"):
        return {
            "ok": False,
            "error": swap.get("error") or "swap failed",
            "funding_plan": plan,
            "swap": swap,
            "stage": "swap",
        }

    post = raydium_clmm.wallet_balance(timeout=25.0)
    return {
        "ok": True,
        "funded": True,
        "funding_plan": plan,
        "swap": swap,
        "balance_after": post if post.get("ok") else None,
    }
