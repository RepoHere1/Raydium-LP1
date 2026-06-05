"""Brainiac LIVE open + USD loss report (network fees vs wallet delta)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL_ID = "AoPimKYHxNTHAXXtqoespdaYVBVvEvjtYNvxGfmRdE2p"
DEPOSIT_USD = 5.0


def wallet_usd(bal: dict, sol_px: float) -> dict:
    sol = float(bal.get("sol_balance") or 0)
    usdc = float(bal.get("usdc_balance") or 0)
    return {
        "sol": sol,
        "usdc": usdc,
        "total_usd": round(sol * sol_px + usdc, 4),
    }


def main() -> int:
    from raydium_lp1.lp_brainiac_cursor_success import (
        apply_brainiac_fee_and_settlement_settings,
        build_brainiac_cursor_open_plan,
        fee_settings_for_brainiac_procedure,
        fund_non_pay_leg_if_needed,
        open_clmm_with_brainiac_cursor_success,
    )
    from raydium_lp1.lp_junk_to_pay import settlement_policy_for_pool
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import wallet_balance
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    load_dotenv()
    if get_mode() != "live":
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
    fee = apply_brainiac_fee_and_settlement_settings(fee_settings_for_brainiac_procedure())
    sol_px = float(fee.get("lp_pay_funding_sol_price_usd") or 180) or 180.0

    pool = fetch_pool_by_id(POOL_ID, config=sc)
    pay = resolve_pay_mint(pool, sc)
    plan = build_brainiac_cursor_open_plan(pool, pool.get("momentum"), settings=fee, scanner=sc)
    settlement = settlement_policy_for_pool(pool, sc)

    before = wallet_balance()
    w0 = wallet_usd(before, sol_px)

    fund = fund_non_pay_leg_if_needed(
        pool,
        target_non_pay_usd=DEPOSIT_USD * 0.35,
        config=sc,
        sol_price_usd=sol_px,
    )
    mid = wallet_balance() if fund.get("ok") and fund.get("signature") else before

    result = open_clmm_with_brainiac_cursor_success(
        pool_id=POOL_ID,
        input_amount_usd=DEPOSIT_USD,
        pool=pool,
        fee_guard_settings=fee,
        sol_price_usd=sol_px,
    )

    after = wallet_balance()
    w1 = wallet_usd(after, sol_px)

    wallet_delta = round(w1["total_usd"] - w0["total_usd"], 4)
    # Negative delta = left wallet (into LP + fees); positive = received
    permanent_loss_usd = round(max(0.0, -wallet_delta - DEPOSIT_USD * 0.0), 4)
    # True "lost" creating position ≈ network fees only if LP value is recoverable:
    # fees ≈ wallet drop minus deposit notional still in position
    network_fee_est = round(max(0.0, -(wallet_delta) - DEPOSIT_USD), 4) if wallet_delta < 0 else 0.0
    if network_fee_est < 0:
        network_fee_est = 0.0

    sig = ""
    if result.get("ok"):
        sig = str(
            (result.get("clmm") or {}).get("signature")
            or (result.get("position") or {}).get("tx")
            or ""
        )

    report = {
        "ok": bool(result.get("ok")),
        "pool_id": POOL_ID,
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "strategy": "brainiac_cursor_success_80_skewed_no_escrow",
        "deposit_usd_requested": DEPOSIT_USD,
        "pay_type_symbol": pay.pay_symbol if pay else None,
        "non_pay_symbol": pay.alt_symbol if pay else None,
        "settlement_policy": settlement,
        "placement": {
            "skew": plan.get("skew"),
            "tick_lower_pct_below": plan.get("tick_lower_pct_below"),
            "tick_upper_pct_above": plan.get("tick_upper_pct_above"),
        },
        "fund_non_pay": fund,
        "open": {
            "ok": result.get("ok"),
            "error": result.get("error"),
            "signature": sig,
            "nft": (result.get("position") or {}).get("position_nft_mint"),
            "wallet_settlement": result.get("wallet_settlement"),
        },
        "wallet_usd": {
            "sol_price_usd": sol_px,
            "before": w0,
            "after": w1,
            "delta_usd": wallet_delta,
            "note": (
                "delta_usd is total wallet (SOL+USDC) change. "
                "Most of a negative delta is LP deposit (recoverable on close), not burned."
            ),
        },
        "permanent_loss_usd": {
            "network_fees_estimated": round(network_fee_est, 4),
            "wallet_delta_usd": wallet_delta,
            "deposit_in_position_usd": DEPOSIT_USD if result.get("ok") else 0,
            "interpretation": (
                f"Estimated non-recoverable cost to open: ~${network_fee_est:.2f} USD (tx fees). "
                f"~${DEPOSIT_USD:.2f} is in the LP position (recoverable when you close)."
            ),
        },
    }
    if result.get("position", {}).get("open_economics"):
        report["open_economics"] = result["position"]["open_economics"]

    print(json.dumps(report, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
