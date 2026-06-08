"""Brainiac placement analysis + LIVE open for one pool (80% wide default)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pool_id")
    parser.add_argument("--usd", type=float, default=3.15)
    parser.add_argument("--width-pct", type=float, default=80.0, help="Wide band total width")
    parser.add_argument(
        "--strategy",
        default="",
        help="Force strategy id (empty = brainiac pick, wide uses standard_full_range)",
    )
    parser.add_argument("--execute", action="store_true", help="Sign and send LIVE open")
    args = parser.parse_args()

    from dataclasses import replace

    from raydium_lp1.fee_guard import reset_session_ledger
    from raydium_lp1.live_executor import live_readiness_check
    from raydium_lp1.lp_live_router import execute_strategy_live_open
    from raydium_lp1.lp_order_strategies import (
        ALL_STRATEGY_IDS,
        STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        STRATEGY_FULL_RANGE,
    )
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.scanner import ScannerConfig, assess_capacity, load_dotenv
    from raydium_lp1.settings_io import load_settings_json
    from raydium_lp1 import wallet as wallet_mod
    from raydium_lp1.super_brainiac.possibilities import (
        BrainiacConfig,
        pool_passes_universe,
        score_strategy_for_pool,
    )
    from raydium_lp1.lp_open_style import resolve_live_open_style
    from raydium_lp1.spend_less_get_more import analyze_open_plan

    load_dotenv()
    settings_path = REPO / "config" / "settings.json"
    scanner = ScannerConfig.from_file(settings_path)
    settings = load_settings_json(settings_path)
    settings = dict(settings)
    settings["fee_guard_enabled"] = True

    pool = fetch_pool_by_id(args.pool_id.strip(), config=scanner)
    dep = float(args.usd)
    bcfg = BrainiacConfig.from_mapping(settings, scanner=scanner)
    bcfg = replace(bcfg, deposit_usd=dep)

    route_ok, route_reasons = pool_passes_universe(pool, bcfg, scanner, check_routes=True)
    rankings = [
        score_strategy_for_pool(pool, sid, cfg=bcfg, scanner=scanner) for sid in ALL_STRATEGY_IDS
    ]
    rankings.sort(key=lambda s: -float(s.get("brainiac_score") or 0))

    best = rankings[0] if rankings else {}
    forced = args.strategy.strip()
    if not forced:
        strategy_id = STRATEGY_BRAINIAC_CURSOR_SUCCESS
        brainiac_note = (
            f"Brainiac 80% skew grid (fee-model leader: {best.get('strategy_id')} "
            f"score {best.get('brainiac_score')}, in_range {best.get('in_range_factor')})."
        )
    else:
        strategy_id = forced
        brainiac_note = f"Forced strategy {strategy_id}"

    width_for_style = float(args.width_pct)
    if strategy_id == STRATEGY_FULL_RANGE:
        width_for_style = min(80.0, width_for_style)
    elif not args.strategy.strip():
        width_for_style = 80.0
    else:
        # Non-wide strategies: do not inherit CLI --width-pct (e.g. 80) from wide requests.
        width_for_style = float(
            (best.get("width_pct") if best else None) or scanner.lp_default_range_width_pct or 20.0
        )

    cfg = replace(
        scanner,
        lp_active_strategy=strategy_id,
        lp_default_range_width_pct=width_for_style,
        lp_skew_use_momentum=True,
        lp_planning_enabled=True,
    )
    style = resolve_live_open_style(cfg, pool)
    if strategy_id == STRATEGY_FULL_RANGE:
        style_kw = dict(style.open_kwargs)
        style_kw["wide_range_width_pct"] = min(80.0, float(args.width_pct))
        half = float(args.width_pct) / 2.0
        style_kw["tick_lower_pct_below"] = half
        style_kw["tick_upper_pct_above"] = half
    else:
        style_kw = dict(style.open_kwargs)

    w = wallet_mod.load_wallet()
    cap = assess_capacity(scanner, w)
    bal = float((cap.get("balance") or {}).get("sol") or 0.0)
    sol_px = float(settings.get("lp_pay_funding_sol_price_usd") or 180) or 180.0
    pay_sym = str(style.open_kwargs.get("pay_symbol") or "USDC").upper()

    sl = analyze_open_plan(
        requested_deposit_usd=dep,
        open_kwargs=style_kw,
        pay_symbol=pay_sym,
        balance_sol=bal,
        reserve_sol=float(getattr(scanner, "reserve_sol", 0.002) or 0.002),
        settings=settings,
        strategy_id=strategy_id,
        sol_price_usd=sol_px,
    )

    report = {
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "liquidity_usd": pool.get("liquidity_usd"),
        "fee_24h_usd": pool.get("fee_24h_usd"),
        "deposit_usd": dep,
        "routes_ok": route_ok,
        "route_reasons": route_reasons,
        "brainiac_note": brainiac_note,
        "strategy_rankings": rankings[:6],
        "chosen_strategy": strategy_id,
        "lp_style": {
            "placement": style.placement,
            "width_pct": style.width_pct,
            "open_kwargs": style_kw,
        },
        "spend_less_get_more": sl.to_dict(),
    }
    from raydium_lp1.raydium_clmm import wallet_balance

    wb = wallet_balance()
    report["wallet_affordability"] = {
        "usdc_balance": float(wb.get("usdc_balance") or 0),
        "sol_balance": float(wb.get("sol_balance") or 0),
        "requested_usd": dep,
        "wide_80_min_usd_rent_cap": sl.min_deposit_usd_rent_cap,
        "spend_less_ok": sl.ok,
        "sol_need_est": sl.sol_need_est,
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / f"brainiac_open_{args.pool_id[:8]}.json"
    plan_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {plan_path}", file=sys.stderr)

    if not args.execute:
        ready = live_readiness_check()
        print(json.dumps({"ready_to_sign": ready.get("ready_to_sign"), "blockers": ready.get("blockers")}, indent=2))
        return 0 if sl.ok and route_ok else 1

    if not route_ok:
        print(json.dumps({"ok": False, "error": "routes failed", "reasons": route_reasons}, indent=2))
        return 1
    if not sl.ok:
        print(json.dumps({"ok": False, "error": "SPEND LESS blocked", "plan": sl.to_dict()}, indent=2))
        return 1

    ready = live_readiness_check()
    if not ready.get("ready_to_sign"):
        print(json.dumps({"ok": False, "blockers": ready.get("blockers")}, indent=2))
        return 1

    reset_session_ledger()
    half = float(args.width_pct) / 2.0
    result = execute_strategy_live_open(
        pool_id=args.pool_id.strip(),
        deposit_usd=float(sl.effective_deposit_usd),
        force_pay_token_only=True if strategy_id != STRATEGY_BRAINIAC_CURSOR_SUCCESS else None,
        strategy_id=strategy_id,
        tick_lower_pct_below=half,
        tick_upper_pct_above=half,
        fee_guard_settings=settings,
        sol_price_usd=sol_px,
    )
    print(json.dumps(result, indent=2, default=str))

    if result.get("ok"):
        from raydium_lp1.lp_tx_cost_analysis import analyze_open_bundle
        from raydium_lp1.raydium_clmm import wallet_balance

        wb = wallet_balance()
        fee_est = (result.get("clmm") or {}).get("fee_guard_estimate") or {}
        rent = fee_est.get("rent_escrow") if isinstance(fee_est, dict) else None
        analysis = analyze_open_bundle(
            result,
            wallet=str(wb.get("address") or ""),
            rpc_url=str(wb.get("rpc_url") or ""),
            rent_escrow_estimate=rent,
            deposit_usd=float(sl.effective_deposit_usd),
        )
        analysis_path = out_dir / f"brainiac_open_{args.pool_id[:8]}_cost.json"
        analysis_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
        learn_path = out_dir / "brainiac_open_learnings.md"
        _append_learnings(learn_path, report, result, analysis)
        print(json.dumps({"cost_analysis_path": str(analysis_path), "learnings_path": str(learn_path)}, indent=2))

    return 0 if result.get("ok") else 1


def _append_learnings(
    path: Path,
    plan: dict,
    result: dict,
    analysis: dict,
) -> None:
    clmm = result.get("clmm") or {}
    lines = [
        f"\n## Open {plan.get('pool_id')} @ ${plan.get('deposit_usd')}\n",
        f"- Pair: {plan.get('pair')}",
        f"- Strategy: {plan.get('chosen_strategy')} | {plan.get('brainiac_note')}",
        f"- Routes: {plan.get('routes_ok')}",
        f"- SPEND LESS ok: {(plan.get('spend_less_get_more') or {}).get('ok')}",
        f"- Tx: {clmm.get('signature') or result.get('signature')}",
        f"- NFT: {clmm.get('position_nft_mint')}",
        f"- Cost analysis keys: {list(analysis.keys())[:12]}",
    ]
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
