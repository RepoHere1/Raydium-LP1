"""CLI: open one LIVE CLMM position (pay-token-only rules, ~25¢ sizing)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _config(*, force_pay_only: bool, strategy: str | None = None):
    from dataclasses import replace

    from raydium_lp1.scanner import ScannerConfig

    config = ScannerConfig.from_file(REPO / "config" / "settings.json")
    if force_pay_only:
        config = replace(config, lp_open_pay_token_only=True)
    if strategy:
        config = replace(
            config,
            lp_active_strategy=strategy,
            lp_skew_use_momentum=True,
            lp_planning_enabled=True,
        )
    return config


def _fee_settings(*, force_fee_guard: bool):
    from raydium_lp1.settings_io import load_settings_json

    settings = load_settings_json(REPO / "config" / "settings.json")
    if force_fee_guard:
        settings = dict(settings)
        settings["fee_guard_enabled"] = True
    return settings


def _preview(
    pool_id: str | None,
    amount_sol: float,
    *,
    force_pay_only: bool = False,
    strategy: str | None = None,
) -> dict:
    from raydium_lp1.live_executor import DEFAULT_LATEST, _pick_candidate, _read_latest
    from raydium_lp1.lp_open_style import resolve_live_open_style
    from raydium_lp1.lp_pay_mint import (
        pay_mint_open_error,
        pay_token_only_enabled,
        resolve_pay_mint,
    )
    config = _config(force_pay_only=force_pay_only, strategy=strategy)
    report = _read_latest(DEFAULT_LATEST)
    pool = _pick_candidate(report, pool_id, config=config)
    pay_res = resolve_pay_mint(pool, config) if pay_token_only_enabled(config) else None
    if pay_token_only_enabled(config) and pay_res is None:
        raise ValueError(pay_mint_open_error(pool, config))
    style = resolve_live_open_style(config, pool)
    manual_check: dict | None = None
    if pool_id and str(pool_id).strip():
        from raydium_lp1.manual_live_open import assert_manual_live_open_allowed

        manual_check = assert_manual_live_open_allowed(pool, config, explicit_pool_id=True)
    return {
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "input_amount_sol": amount_sol,
        "lp_open_pay_token_only": pay_token_only_enabled(config),
        "pay_symbol": pay_res.pay_symbol if pay_res else None,
        "pay_mint": pay_res.pay_mint if pay_res else None,
        "lp_style_label": style.lp_style_label,
        "lp_strategy_id": getattr(config, "lp_active_strategy", None),
        "lp_placement": style.placement,
        "manual_live_check": manual_check,
        "style_open_kwargs": dict(style.open_kwargs),
        "open_kwargs": {
            k: style.open_kwargs.get(k)
            for k in (
                "single_side",
                "input_mint",
                "pay_mint_only",
                "pay_symbol",
                "single_side_width_pct",
                "band_tick_steps",
                "wide_range",
                "wide_range_width_pct",
                "literal_pool_full_range",
            )
            if k in style.open_kwargs
        },
    }


def _resolve_amount_sol(args: argparse.Namespace) -> float:
    if args.use_min_deposit:
        from raydium_lp1.fee_guard import fee_config_from_settings

        return float(fee_config_from_settings().min_clmm_deposit_sol)
    if args.sol is not None:
        return float(args.sol)
    if args.amount_pos is not None:
        return float(args.amount_pos)
    usd = 0.25 if args.usd is None else float(args.usd)
    price = float(args.sol_price)
    if price <= 0:
        raise ValueError("sol-price must be > 0")
    return usd / price


def main() -> int:
    from raydium_lp1.fee_guard import (
        FeeGuardBlockedError,
        assert_clmm_open_allowed,
        estimate_clmm_open_cost_sol,
        fee_config_from_settings,
    )
    from raydium_lp1.live_executor import live_readiness_check
    from raydium_lp1.lp_live_router import execute_strategy_live_open
    from raydium_lp1.manual_live_open import ManualLiveBlockedError
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.scanner import load_dotenv

    parser = argparse.ArgumentParser(
        description="LIVE CLMM open (SOL/USDC/USDT deposit only when lp_open_pay_token_only is on).",
    )
    parser.add_argument("pool_id", nargs="?", default="", help="Raydium pool id (empty = top candidate)")
    parser.add_argument(
        "amount_pos",
        nargs="?",
        default=None,
        help="Deposit size in SOL (legacy 2nd positional)",
    )
    parser.add_argument("--usd", type=float, default=None, help="Deposit notional in USD (default 0.25)")
    parser.add_argument("--sol", type=float, default=None, help="Deposit size in SOL (overrides --usd)")
    parser.add_argument(
        "--sol-price",
        type=float,
        default=float(os.environ.get("SOL_USD_PRICE", "180") or 180),
        help="SOL/USD for --usd sizing (env SOL_USD_PRICE)",
    )
    parser.add_argument("--preview-only", action="store_true", help="Print plan only; do not sign")
    parser.add_argument(
        "--force-pay-only",
        action="store_true",
        help="Deposit SOL/USDC/USDT only for this open (overrides lp_open_pay_token_only off)",
    )
    parser.add_argument(
        "--use-min-deposit",
        action="store_true",
        help="Use min_clmm_deposit_sol from settings (fee guard minimum; 25¢ opens are blocked)",
    )
    parser.add_argument(
        "--force-fee-guard",
        action="store_true",
        help="Apply fee_guard_enabled=true for this open (blocks micro-deposits)",
    )
    parser.add_argument(
        "--strategy",
        default="",
        help="LP strategy id for this open (e.g. trailing_dynamic_skew = Dynamic Skew Order)",
    )
    args = parser.parse_args()

    load_dotenv()
    mode = get_mode()
    if mode != "live" and not args.preview_only:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"mode is {mode!r}; set config/settings.json mode to live",
                },
                indent=2,
            )
        )
        return 1

    ready = live_readiness_check()
    if not ready.get("ready_to_sign") and not args.preview_only:
        print(json.dumps({"ok": False, "blockers": ready.get("blockers")}, indent=2))
        return 1

    pool_id = args.pool_id.strip() or None
    amount_sol = _resolve_amount_sol(args)
    strategy = args.strategy.strip() or None
    fee_settings = _fee_settings(force_fee_guard=bool(args.force_fee_guard))

    try:
        plan = _preview(
            pool_id,
            amount_sol,
            force_pay_only=bool(args.force_pay_only),
            strategy=strategy,
        )
        from raydium_lp1.lp_rent_escrow import estimate_open_rent_escrow

        fee_cfg = fee_config_from_settings(fee_settings)
        dep_usd = float(args.usd) if args.usd is not None else amount_sol * float(args.sol_price)
        dep_sol = dep_usd / float(args.sol_price)
        style_kw = plan.get("style_open_kwargs") or {}
        plan["fee_guard"] = estimate_clmm_open_cost_sol(fee_cfg, deposit_sol=dep_sol)
        plan["rent_escrow"] = estimate_open_rent_escrow(
            deposit_sol=dep_sol,
            open_kwargs=style_kw,
            settings=fee_settings,
        ).to_dict()
        plan["fee_guard_session"] = __import__(
            "raydium_lp1.fee_guard", fromlist=["session_summary"]
        ).session_summary(fee_cfg)
        if not args.preview_only:
            assert_clmm_open_allowed(dep_sol, settings=fee_settings, open_kwargs=style_kw)
        else:
            try:
                assert_clmm_open_allowed(dep_sol, settings=fee_settings, open_kwargs=style_kw)
                plan["fee_guard_ok"] = True
            except FeeGuardBlockedError as exc:
                plan["fee_guard_ok"] = False
                plan["fee_guard_block_reason"] = str(exc)
    except FeeGuardBlockedError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "fee_guard": True}, indent=2))
        return 1
    except ManualLiveBlockedError as exc:
        detail = getattr(exc, "detail", None) or {}
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "manual_live_blocked": True,
                    "notification": detail.get("alert_path"),
                    "manual_live_detail": detail,
                },
                indent=2,
            )
        )
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    print(json.dumps({"plan": plan}, indent=2))
    if args.preview_only:
        return 0

    dep_usd = float(args.usd) if args.usd is not None else amount_sol * float(args.sol_price)
    result = execute_strategy_live_open(
        pool_id=pool_id,
        input_amount_sol=amount_sol,
        deposit_usd=(None if args.usd is None else float(args.usd)),
        force_pay_token_only=True if args.force_pay_only else None,
        strategy_id=strategy,
        fee_guard_settings=fee_settings if args.force_fee_guard else None,
        sol_price_usd=float(args.sol_price),
    )
    print(json.dumps(result, indent=2, default=str))
    if result.get("ok"):
        try:
            from raydium_lp1.lp_tx_cost_analysis import analyze_open_bundle
            from raydium_lp1.raydium_clmm import wallet_balance

            wb = wallet_balance()
            fee_est = (result.get("clmm") or {}).get("fee_guard_estimate") or {}
            rent = fee_est.get("rent_escrow") if isinstance(fee_est, dict) else plan.get("rent_escrow")
            analysis = analyze_open_bundle(
                result,
                wallet=str(wb.get("address") or ""),
                rpc_url=str(wb.get("rpc_url") or ""),
                rent_escrow_estimate=rent,
                deposit_usd=dep_usd,
            )
            out_path = REPO / "reports" / "last_open_cost_analysis.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"cost_analysis": analysis, "report_path": str(out_path)}, indent=2))
        except Exception as exc:
            print(json.dumps({"cost_analysis_error": str(exc)}, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
