"""Pre-trade Brainiac analysis — feasibility, costs, improvements (no on-chain spend)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL_ID = sys.argv[1] if len(sys.argv) > 1 else ""
DEPOSIT_USD = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0


def main() -> int:
    if not POOL_ID:
        print(json.dumps({"ok": False, "error": "pool id required"}))
        return 1

    from dataclasses import replace

    from raydium_lp1.fee_guard import (
        estimate_clmm_open_cost_sol,
        fee_config_from_settings,
        session_summary,
    )
    from raydium_lp1.live_executor import live_readiness_check
    from raydium_lp1.lp_brainiac_cursor_success import (
        apply_brainiac_fee_and_settlement_settings,
        build_brainiac_cursor_open_plan,
        fee_settings_for_brainiac_procedure,
        open_kwargs_from_plan,
        resolve_brainiac_live_auto_policy,
    )
    from raydium_lp1.lp_junk_to_pay import settlement_policy_for_pool
    from raydium_lp1.lp_open_style import resolve_live_open_style
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.lp_rent_escrow import estimate_open_rent_escrow
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.manual_live_open import assert_manual_live_open_allowed
    from raydium_lp1.raydium_clmm import wallet_balance
    from raydium_lp1.scanner import ScannerConfig, load_dotenv
    from raydium_lp1.spend_less_get_more import analyze_open_plan

    load_dotenv()
    sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
    sc = replace(
        sc,
        lp_active_strategy="brainiac_cursor_success_80_skewed_no_escrow",
        lp_skew_use_momentum=True,
        lp_planning_enabled=True,
    )
    fee = apply_brainiac_fee_and_settlement_settings(fee_settings_for_brainiac_procedure())
    sol_px = float(fee.get("lp_pay_funding_sol_price_usd") or 180) or 180.0

    pool = fetch_pool_by_id(POOL_ID, config=sc)
    pay = resolve_pay_mint(pool, sc)
    plan = build_brainiac_cursor_open_plan(pool, pool.get("momentum"), settings=fee, scanner=sc)
    auto = resolve_brainiac_live_auto_policy(DEPOSIT_USD, pool=pool, settings=fee)
    kw = open_kwargs_from_plan(
        plan,
        deposit_usd=DEPOSIT_USD,
        band_tick_steps_cap=auto.band_tick_steps_cap,
    )
    style = resolve_live_open_style(sc, pool)
    settlement = settlement_policy_for_pool(pool, sc)

    wb = wallet_balance()
    sol = float(wb.get("sol_balance") or 0)
    usdc = float(wb.get("usdc_balance") or 0)
    pay_sym = pay.pay_symbol if pay else "SOL"
    dep_human = DEPOSIT_USD if pay_sym in ("USDC", "USDT", "USD1") else DEPOSIT_USD / sol_px

    sl = analyze_open_plan(
        requested_deposit_usd=DEPOSIT_USD,
        open_kwargs=kw,
        pay_symbol=pay_sym,
        balance_sol=sol,
        reserve_sol=0.05,
        settings=fee,
        strategy_id="brainiac_cursor_success_80_skewed_no_escrow",
        sol_price_usd=sol_px,
    )
    fee_cfg = fee_config_from_settings(fee)
    fee_est = estimate_clmm_open_cost_sol(
        fee_cfg,
        deposit_sol=DEPOSIT_USD / sol_px,
        priority_micro=fee_cfg.max_priority_fee_micro_lamports,
    )
    rent = estimate_open_rent_escrow(
        deposit_sol=DEPOSIT_USD / sol_px,
        open_kwargs=kw,
        settings=fee,
    )

    from raydium_lp1.lp_junk_to_pay import non_pay_wallet_inventory_usd

    inv = non_pay_wallet_inventory_usd(pool, sc, sol_price_usd=sol_px)
    fund_pct = int(round(auto.fund_non_pay_fraction * 100))
    fund_usd_est = (
        0.0
        if auto.skip_fund_swap
        else round(DEPOSIT_USD * auto.fund_non_pay_fraction, 2)
    )
    issues = []
    improvements = []

    tvl = float(pool.get("liquidity_usd") or 0)
    fee24 = float(pool.get("fee_24h_usd") or pool.get("fee24h") or 0)
    if DEPOSIT_USD < 2.0 and not auto.skip_fund_swap:
        issues.append(
            f"Deposit ${DEPOSIT_USD:.2f} two-sided: will fund ~${fund_usd_est} {inv.get('symbol')} from SOL "
            f"(wallet has ~${float(inv.get('usd') or 0):.2f}) — small size 6017 risk on memecoin pools."
        )
    elif DEPOSIT_USD < 2.0 and auto.skip_fund_swap:
        issues.append(
            f"Deposit ${DEPOSIT_USD:.2f} two-sided: wallet already holds ~${float(inv.get('usd') or 0):.2f} "
            f"{inv.get('symbol')} — fund swap skipped."
        )
        improvements.append(
            "For sub-$2: prefer single-sided pay-only band OR add-liquidity to existing NFT "
            "instead of new wallet_inventory open (saves 1 Jupiter tx + ghost NFT risk)."
        )
    if fund_usd_est + 0.02 > usdc and pay_sym == "USDC":
        issues.append(f"USDC ${usdc:.2f} may be tight after ~${fund_usd_est} fund swap + open.")
        improvements.append("Pre-hold ZINC in-wallet to skip USDC→alt Jupiter (saves ~$0.05–0.30 + slippage).")
    if sl.effective_deposit_usd < DEPOSIT_USD:
        issues.append(f"SPEND LESS may clamp deposit to ${sl.effective_deposit_usd:.2f}.")
    if not sl.ok:
        issues.append(f"SPEND LESS blocks: {sl.blocks}")
    if sol < 0.12:
        issues.append(f"SOL {sol:.4f} low for rent buffer + failed-tx retries.")
        improvements.append("Keep ≥0.12 SOL headroom; position rent is recoverable but txs need native SOL.")

    improvements.extend([
        "Raydium 80% skew grid is for fee APR model — on-chain min liquidity per tick may reject "
        "tiny two-sided deposits even when UI 'works' at higher size.",
        f"Brainiac auto policy: fund={auto.fund_non_pay_fraction:.2f} skip_fund={auto.skip_fund_swap} "
        f"min_in_range={auto.min_in_range_factor}.",
        "If 6017: widen slippage_bps temporarily or narrow band_tick_steps (fewer tick arrays = less rent).",
    ])

    manual = None
    try:
        manual = assert_manual_live_open_allowed(pool, sc, explicit_pool_id=True)
    except Exception as exc:
        manual = {"blocked": str(exc)}

    out = {
        "ok": pay is not None and sl.ok,
        "pool_id": POOL_ID,
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "deposit_usd": DEPOSIT_USD,
        "pay_type": pay.pay_symbol if pay else None,
        "non_pay": pay.alt_symbol if pay else None,
        "pool_stats": {
            "liquidity_usd": tvl,
            "fee_24h_usd": fee24,
            "apr": pool.get("apr"),
            "share_of_fees_if_in_range": round(fee24 * (DEPOSIT_USD / tvl), 4) if tvl > 0 else None,
        },
        "wallet": {"sol": sol, "usdc": usdc, "total_usd": round(sol * sol_px + usdc, 2)},
        "placement": {
            "skew": plan.get("skew"),
            "tick_lower_pct_below": plan.get("tick_lower_pct_below"),
            "tick_upper_pct_above": plan.get("tick_upper_pct_above"),
            "leader_apr_model": (plan.get("brainiac_placement") or {}).get("fee_model_leader"),
            "in_range_factor": (plan.get("brainiac_placement") or {}).get("in_range_factor_at_skew"),
        },
        "open_kwargs_summary": {
            k: kw.get(k)
            for k in (
                "wallet_inventory_full_range",
                "tick_lower_pct_below",
                "tick_upper_pct_above",
                "band_tick_steps",
            )
        },
        "spend_less": sl.to_dict(),
        "fee_guard_open_est": fee_est,
        "rent_escrow_est": rent.to_dict(),
        "fund_non_pay_est_usd": fund_usd_est,
        "settlement": settlement,
        "live_readiness": live_readiness_check(),
        "manual_live": manual,
        "fee_session": session_summary(fee_cfg),
        "issues": issues,
        "improvements": improvements,
        "proceed_recommendation": (
            "CAUTION: proceed only if SPEND LESS ok and USDC covers fund+open; "
            "expect high 6017 risk at $1 two-sided."
            if DEPOSIT_USD < 2
            else "Proceed if SPEND LESS ok."
        ),
    }
    compact = __import__("os").environ.get("BRAINIAC_JSON_COMPACT", "").lower() in ("1", "true", "yes")
    if compact:
        print(json.dumps(out, default=str))
    else:
        print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
