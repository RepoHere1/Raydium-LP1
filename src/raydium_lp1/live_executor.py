"""Open verified CLMM candidates on-chain when mode=LIVE (requires signer in .env)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from raydium_lp1.fee_guard import FeeGuardBlockedError, assert_clmm_open_allowed, fee_config_from_settings
from raydium_lp1.live_guard import guard_onchain
from raydium_lp1.mode_toggle import ModeBlockedError
from raydium_lp1.scanner import load_dotenv

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_LATEST = REPO / "reports" / "latest.json"
ACTIVE_POSITIONS_PATH = REPO / "active_positions.json"
WSOL_MINT = "So11111111111111111111111111111111111111112"

_CLMM_OPEN_PARAM_KEYS = frozenset({
    "pool_id",
    "input_mint",
    "input_amount_human",
    "tick_lower_pct_below",
    "tick_upper_pct_above",
    "slippage_bps",
    "priority_fee_micro_lamports",
    "single_side",
    "single_side_start_pct",
    "single_side_width_pct",
    "band_tick_steps",
    "min_tick_steps",
    "pay_mint_only",
    "full_range",
    "wide_range",
    "wide_range_width_pct",
    "literal_pool_full_range",
    "slippage_bps",
    "wallet_inventory_full_range",
    "wallet_inventory_wide_range",
    "total_budget_usd",
})


def _build_clmm_open_kwargs(
    style_open: dict[str, Any],
    *,
    pool_id: str,
    input_mint: str,
    input_amount_human: float,
    tick_lower_pct_below: float,
    tick_upper_pct_above: float,
) -> dict[str, Any]:
    """Merge LP style kwargs with required open fields (no duplicate dict() keys)."""

    merged = dict(style_open)
    for meta in ("pay_symbol", "_lp_placement"):
        merged.pop(meta, None)
    merged.update(
        {
            "pool_id": pool_id,
            "input_mint": input_mint,
            "input_amount_human": input_amount_human,
        }
    )
    if not merged.get("single_side"):
        merged.setdefault("tick_lower_pct_below", tick_lower_pct_below)
        merged.setdefault("tick_upper_pct_above", tick_upper_pct_above)
    return {k: merged[k] for k in merged if k in _CLMM_OPEN_PARAM_KEYS}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_latest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing scan report: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("latest.json must be an object")
    return data


def _pick_candidate(
    report: dict[str, Any],
    pool_id: str | None,
    *,
    config: Any | None = None,
) -> dict[str, Any]:
    from raydium_lp1.lp_selection import pick_live_candidate

    if config is None:
        from raydium_lp1.scanner import ScannerConfig

        config = ScannerConfig.from_file(REPO / "config" / "settings.json")
    return pick_live_candidate(report, pool_id, config=config, fetch_if_missing=True)


def _sol_mint_for_pool(pool: dict[str, Any]) -> str:
    a = str(pool.get("mint_a") or "")
    b = str(pool.get("mint_b") or "")
    sym_a = str(pool.get("mint_a_symbol") or "").upper()
    sym_b = str(pool.get("mint_b_symbol") or "").upper()
    if sym_a in ("SOL", "WSOL") and a:
        return a
    if sym_b in ("SOL", "WSOL") and b:
        return b
    return WSOL_MINT


def live_readiness_check() -> dict[str, Any]:
    from raydium_lp1.tune_advisor import _live_readiness
    from raydium_lp1.settings_io import load_settings_json

    load_dotenv()
    settings = load_settings_json(REPO / "config" / "settings.json")
    return _live_readiness(settings)


def _resolve_deposit_human(
    pos_sol: float,
    pay_res: Any | None,
    *,
    usd_notional: float | None = None,
    sol_price_usd: float | None = None,
) -> float:
    """Map CLI sizing to the pay-token human amount the Raydium SDK expects."""

    sym = str(getattr(pay_res, "pay_symbol", "") or "").upper()
    if usd_notional is not None and usd_notional > 0:
        if sym in ("USDC", "USDT", "USD1"):
            return float(usd_notional)
        if sym in ("SOL", "WSOL"):
            px = float(sol_price_usd or 180.0)
            return float(usd_notional) / px if px > 0 else float(pos_sol)
    return float(pos_sol)


def open_clmm_candidate(
    *,
    pool_id: str | None = None,
    latest_path: Path = DEFAULT_LATEST,
    input_amount_sol: float | None = None,
    input_amount_usd: float | None = None,
    wallet_inventory_full_range: bool = False,
    tick_lower_pct_below: float = 12.0,
    tick_upper_pct_above: float = 12.0,
    force_pay_token_only: bool | None = None,
    strategy_id: str | None = None,
    fee_guard_settings: dict[str, Any] | None = None,
    sol_price_usd: float | None = None,
    open_deposit_usd: float | None = None,
    band_tick_steps_cap: int | None = None,
    skip_wallet_settlement: bool = False,
) -> dict[str, Any]:

    try:
        guard_onchain("CLMM open_position")
    except ModeBlockedError as exc:
        return {"ok": False, "error": str(exc), "mode_blocked": True}

    load_dotenv()
    readiness = live_readiness_check()
    if not readiness.get("ready_to_sign"):
        return {
            "ok": False,
            "error": "live not ready",
            "blockers": readiness.get("blockers"),
            "readiness": readiness,
        }

    from raydium_lp1 import raydium_clmm
    from raydium_lp1.scanner import ScannerConfig, assess_capacity
    from raydium_lp1 import wallet as wallet_mod

    from dataclasses import replace

    settings_path = REPO / "config" / "settings.json"
    config = ScannerConfig.from_file(settings_path)
    if force_pay_token_only is not None:
        config = replace(config, lp_open_pay_token_only=bool(force_pay_token_only))
    if strategy_id:
        config = replace(
            config,
            lp_active_strategy=strategy_id,
            lp_skew_use_momentum=True,
            lp_planning_enabled=True,
        )
    explicit_pool = bool(pool_id and str(pool_id).strip())
    manual_check: dict[str, Any] | None = None
    report = _read_latest(latest_path)
    pool = _pick_candidate(report, pool_id, config=config)
    from raydium_lp1.lp_order_rules import pool_open_blocked

    if explicit_pool:
        from raydium_lp1.manual_live_open import ManualLiveBlockedError, assert_manual_live_open_allowed

        try:
            manual_check = assert_manual_live_open_allowed(
                pool, config, explicit_pool_id=True
            )
        except ManualLiveBlockedError as exc:
            detail = getattr(exc, "detail", None) or {}
            return {
                "ok": False,
                "error": str(exc),
                "manual_live_blocked": True,
                "notification": detail.get("alert_path"),
                "manual_live_detail": detail,
            }

    block_msg = pool_open_blocked(str(pool.get("id") or ""), config)
    if block_msg:
        return {"ok": False, "error": block_msg, "pool_id": pool.get("id")}
    pv = pool.get("pool_verification") or {}
    if pv and not pv.get("ok", True):
        return {"ok": False, "error": "pool failed verification", "pool": pool.get("id"), "verification": pv}
    w = wallet_mod.load_wallet()
    cap = assess_capacity(config, w)
    bal_sol = float((cap.get("balance") or {}).get("sol") or 0.0)
    pos_sol = float(input_amount_sol if input_amount_sol is not None else config.position_size_sol)
    reserve = float(config.reserve_sol)

    from raydium_lp1.lp_open_style import resolve_live_open_style
    from raydium_lp1.lp_order_strategies import STRATEGY_BRAINIAC_CURSOR_SUCCESS
    from raydium_lp1.lp_pay_mint import pay_mint_open_error, pay_token_only_enabled, resolve_pay_mint

    active_sid = str(strategy_id or getattr(config, "lp_active_strategy", "") or "")
    if active_sid == STRATEGY_BRAINIAC_CURSOR_SUCCESS:
        force_pay_token_only = False
        wallet_inventory_full_range = True

    dep_usd_for_style = float(open_deposit_usd or input_amount_usd or 0) or None
    lp_style = resolve_live_open_style(
        config,
        pool,
        open_deposit_usd=dep_usd_for_style,
        band_tick_steps_cap=band_tick_steps_cap,
    )
    style_open = dict(lp_style.open_kwargs)

    if pay_token_only_enabled(config):
        pay_res = resolve_pay_mint(pool, config)
        if pay_res is None:
            return {"ok": False, "error": pay_mint_open_error(pool, config)}
    else:
        pay_res = resolve_pay_mint(pool, config)

    from raydium_lp1.settings_io import load_settings_json

    from raydium_lp1.no_escrow_policy import normalize_settings_no_escrow

    fee_settings = normalize_settings_no_escrow(
        fee_guard_settings if fee_guard_settings is not None else load_settings_json(settings_path)
    )
    fee_cfg = fee_config_from_settings(fee_settings)
    sol_px_guard = float(sol_price_usd or fee_cfg.sol_price_usd or 180.0)

    input_mint = str(style_open.get("input_mint") or (pay_res.pay_mint if pay_res else _sol_mint_for_pool(pool)))
    deposit_human = _resolve_deposit_human(
        pos_sol, pay_res, usd_notional=input_amount_usd, sol_price_usd=sol_px_guard
    )

    pay_sym = str(getattr(pay_res, "pay_symbol", "") or "").upper() if pay_res else "SOL"

    use_inventory = bool(wallet_inventory_full_range)
    if use_inventory:
        style_open = dict(style_open)
        style_open["wallet_inventory_full_range"] = True
        style_open["total_budget_usd"] = float(input_amount_usd or deposit_human)
        style_open["pay_mint_only"] = False

    open_kwargs = _build_clmm_open_kwargs(
        style_open,
        pool_id=str(pool["id"]),
        input_mint=input_mint,
        input_amount_human=deposit_human,
        tick_lower_pct_below=tick_lower_pct_below,
        tick_upper_pct_above=tick_upper_pct_above,
    )
    if use_inventory:
        open_kwargs["wallet_inventory_full_range"] = True
        open_kwargs["total_budget_usd"] = float(input_amount_usd or deposit_human)
        open_kwargs["pay_mint_only"] = False
    open_kwargs["priority_fee_micro_lamports"] = fee_cfg.max_priority_fee_micro_lamports

    spend_plan: dict[str, Any] | None = None
    from raydium_lp1.spend_less_get_more import (
        TAG as SPEND_LESS_TAG,
        analyze_open_plan,
        attach_post_open_analysis,
        enforce_open_plan,
    )

    if input_amount_usd is not None:
        req_usd = float(input_amount_usd)
    elif pay_sym in ("USDC", "USDT", "USD1"):
        req_usd = float(deposit_human)
    else:
        req_usd = float(deposit_human) * sol_px_guard
    sl = analyze_open_plan(
        requested_deposit_usd=req_usd,
        open_kwargs=open_kwargs,
        pay_symbol=pay_sym,
        balance_sol=bal_sol,
        reserve_sol=reserve,
        settings=fee_settings,
        strategy_id=strategy_id or getattr(config, "lp_active_strategy", None),
        sol_price_usd=sol_px_guard,
    )
    spend_plan = sl.to_dict()

    if sl.strategy_override and sl.strategy_override != getattr(config, "lp_active_strategy", None):
        config = replace(
            config,
            lp_active_strategy=sl.strategy_override,
            lp_skew_use_momentum=True,
            lp_planning_enabled=True,
        )
        lp_style = resolve_live_open_style(
            config,
            pool,
            open_deposit_usd=dep_usd_for_style,
            band_tick_steps_cap=band_tick_steps_cap,
        )
        style_open = dict(lp_style.open_kwargs)
        open_kwargs = _build_clmm_open_kwargs(
            style_open,
            pool_id=str(pool["id"]),
            input_mint=input_mint,
            input_amount_human=deposit_human,
            tick_lower_pct_below=tick_lower_pct_below,
            tick_upper_pct_above=tick_upper_pct_above,
        )
        open_kwargs["priority_fee_micro_lamports"] = fee_cfg.max_priority_fee_micro_lamports
        sl = analyze_open_plan(
            requested_deposit_usd=req_usd,
            open_kwargs=open_kwargs,
            pay_symbol=pay_sym,
            balance_sol=bal_sol,
            reserve_sol=reserve,
            settings=fee_settings,
            strategy_id=sl.strategy_override,
            sol_price_usd=sol_px_guard,
        )
        spend_plan = sl.to_dict()

    if sl.clamped or sl.effective_deposit_usd != req_usd:
        input_amount_usd = sl.effective_deposit_usd
        deposit_human = _resolve_deposit_human(
            pos_sol, pay_res, usd_notional=input_amount_usd, sol_price_usd=sol_px_guard
        )
        open_kwargs["input_amount_human"] = deposit_human

    if not sl.ok:
        try:
            enforce_open_plan(sl)
        except FeeGuardBlockedError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "fee_guard": True,
                "spend_less_get_more": spend_plan,
                "hint": spend_plan.get("recommendations", [None])[0]
                if spend_plan.get("recommendations")
                else f"{SPEND_LESS_TAG}: see spend_less_get_more in response.",
            }

    dep_sol_for_guard = sl.effective_deposit_sol
    try:
        fee_est = assert_clmm_open_allowed(
            dep_sol_for_guard,
            settings=fee_settings,
            open_kwargs=open_kwargs,
        )
        open_cost_sol = float(fee_est.get("estimated_total_sol") or 0.055)
        if sl.sol_need_est > 0:
            # Pay-token funding precheck: legacy fee_est rent_sol (~0.055) over-reserves SOL
            # vs SPEND LESS rent model (~0.02–0.03 on small asymmetric opens).
            open_cost_sol = min(open_cost_sol, float(sl.sol_need_est) + 0.005)
    except FeeGuardBlockedError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "fee_guard": True,
            "spend_less_get_more": spend_plan,
            "hint": (
                "CLMM rent/escrow guard blocked this open. Check rent_escrow in spend_less_get_more, "
                "raise deposit size, narrow the band, or adjust max_rent_escrow_pct_of_deposit in settings."
            ),
        }

    funding_result: dict[str, Any] | None = None
    if pay_res is not None and pay_sym not in ("SOL", "WSOL"):
        from raydium_lp1.pay_token_funding import ensure_pay_token_for_open

        funding_result = ensure_pay_token_for_open(
            pay_res,
            deposit_human,
            config=config,
            fee_settings=fee_settings,
            reserve_sol=reserve,
            open_cost_sol=open_cost_sol,
            sol_price_usd=sol_price_usd,
        )
        if not funding_result.get("ok"):
            return {
                "ok": False,
                "error": funding_result.get("error") or "pay-token funding failed",
                "pay_funding": funding_result,
                "fee_guard_estimate": fee_est,
            }
        cap = assess_capacity(config, w)
        bal_sol = float((cap.get("balance") or {}).get("sol") or 0.0)

    if sl.sol_need_est > 0 and bal_sol + 1e-9 < sl.sol_need_est:
        return {
            "ok": False,
            "error": (
                f"{SPEND_LESS_TAG}: wallet {bal_sol:.4f} SOL < need ~{sl.sol_need_est:.4f} SOL "
                f"for ${sl.effective_deposit_usd:.2f} deposit + rent."
            ),
            "balance_sol": bal_sol,
            "spend_less_get_more": spend_plan,
            "fee_guard_estimate": fee_est,
            "hint": spend_plan.get("recommendations", ["Top up SOL or lower deposit."])[0],
        }
    if funding_result and funding_result.get("funded"):
        plan = funding_result.get("funding_plan") or {}
        sol_need_extra = reserve + float(plan.get("estimated_sol_swap") or 0.0) + open_cost_sol
        if bal_sol + 1e-9 < sol_need_extra:
            return {
                "ok": False,
                "error": (
                    f"insufficient SOL: balance={bal_sol:.4f} need ~{sol_need_extra:.4f} "
                    "(reserve + CLMM rent/fees + optional pay-token swap)"
                ),
                "balance_sol": bal_sol,
                "pay_funding": funding_result,
                "fee_guard_estimate": fee_est,
                "spend_less_get_more": spend_plan,
            }

    result: dict[str, Any] = {"ok": False, "error": "open not attempted"}
    retry_extras: list[dict[str, Any]] = [{}]
    wide_pay_only_fallback = False
    if (
        style_open.get("wide_range")
        and style_open.get("pay_mint_only")
        and pay_res is not None
    ):
        w = float(style_open.get("wide_range_width_pct") or 80)
        retry_extras.append(
            {
                "single_side": "above" if pay_res.pay_is_mint_a else "below",
                "single_side_start_pct": float(style_open.get("single_side_start_pct") or 0.5),
                "single_side_width_pct": w,
                "wide_range": False,
                "full_range": False,
                "literal_pool_full_range": False,
                "band_tick_steps": max(15, int(style_open.get("band_tick_steps") or 42)),
            }
        )
    if fee_cfg.max_open_retries > 1 and style_open.get("single_side"):
        w = float(style_open.get("single_side_width_pct") or lp_style.width_pct)
        retry_extras.append(
            {
                "single_side_width_pct": min(55.0, w * 1.2),
                "band_tick_steps": int(style_open.get("band_tick_steps", 10)) + 4,
            }
        )
    elif fee_cfg.max_open_retries > 1 and not (
        style_open.get("wide_range") or style_open.get("full_range")
    ):
        half = float(style_open.get("tick_lower_pct_below") or lp_style.width_pct / 2)
        retry_extras.append(
            {
                "tick_lower_pct_below": min(45.0, half * 1.15),
                "tick_upper_pct_above": min(45.0, half * 1.15),
                "band_tick_steps": int(style_open.get("band_tick_steps", 10)) + 4,
            }
        )

    max_attempts = max(len(retry_extras), max(1, fee_cfg.max_open_retries))
    for idx, extra in enumerate(retry_extras[:max_attempts]):
        attempt = {**open_kwargs, **extra}
        result = raydium_clmm.open_position(**attempt, fee_guard_settings=fee_settings)
        if result.get("ok"):
            if idx > 0 and extra.get("single_side"):
                wide_pay_only_fallback = True
                result["wide_pay_only_single_side_fallback"] = True
            break
        if result.get("fee_guard"):
            break
        if not fee_cfg.allow_fee_retry_after_failed_tx and (idx + 1) >= len(
            retry_extras[:max_attempts]
        ):
            break
    if not result.get("ok"):
        err = result.get("error") or (result.get("clmm") or {}).get("confirm_error")
        if err and "Custom" in str(err):
            result["hint"] = (
                "On-chain tx failed (often insufficient SOL for position rent + tx fee). "
                "Keep ~0.02–0.03 SOL in wallet; position rent is recoverable on close."
            )
        out = {
            "ok": False,
            "error": err or "CLMM open failed",
            "clmm": result,
            "fee_guard_estimate": fee_est,
            "spend_less_get_more": spend_plan,
        }
        out = attach_post_open_analysis(
            out,
            plan=sl,
            deposit_usd=sl.effective_deposit_usd,
            settings=fee_settings,
        )
        try:
            from raydium_lp1.lp_position_economics import record_failed_open_from_result

            record_failed_open_from_result(
                str(pool.get("id") or ""),
                out,
                sol_price=float(sol_price_usd or fee_cfg.sol_price_usd or 180.0),
            )
        except Exception:
            pass
        return out

    row = {
        "opened_at": _now_iso(),
        "manual_live_check": manual_check if explicit_pool else None,
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "apr": pool.get("apr"),
        "liquidity_usd": pool.get("liquidity_usd"),
        "fee_24h_usd": pool.get("fee_24h_usd"),
        "input_amount_sol": dep_sol_for_guard,
        "input_amount_human": deposit_human,
        "input_pay_symbol": getattr(pay_res, "pay_symbol", None) if pay_res else None,
        "position_nft_mint": result.get("position_nft_mint") or result.get("nftMint"),
        "tx": result.get("tx") or result.get("signature"),
        "clmm_result": result,
        "status": "live_open",
        "momentum": pool.get("momentum"),
        **lp_style.to_position_fields(),
    }
    if wide_pay_only_fallback:
        row["wide_pay_only_single_side_fallback"] = True
        row["lp_open_note"] = (
            "Wide 80% straddle needs ALT leg; opened single-sided SOL band at same width "
            "(standard_full_range pay-only)."
        )
    if spend_plan is not None:
        row["spend_less_get_more"] = spend_plan
    if funding_result is not None:
        row["pay_funding"] = funding_result
    out_ok: dict[str, Any] = {
        "ok": True,
        "position": row,
        "clmm": result,
        "fee_guard_estimate": fee_est,
        "spend_less_get_more": spend_plan,
    }
    if funding_result is not None:
        out_ok["pay_funding"] = funding_result
    from raydium_lp1.lp_brainiac_cursor_success import (
        STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        settle_wallet_after_brainiac_trade,
    )
    from raydium_lp1.lp_junk_to_pay import keep_mints_for_pool
    from raydium_lp1.lp_wallet_settlement import settle_wallet_after_trade

    if str(strategy_id or "").strip() == STRATEGY_BRAINIAC_CURSOR_SUCCESS:
        if not skip_wallet_settlement:
            out_ok["wallet_settlement"] = settle_wallet_after_brainiac_trade(
                pool,
                config,
                sol_price_usd=sol_price_usd,
                fee_settings=fee_settings,
            )
    else:
        out_ok["wallet_settlement"] = settle_wallet_after_trade(
            pool=pool,
            config=config,
            sol_price_usd=sol_price_usd,
            fee_settings=fee_settings,
            keep_mints=keep_mints_for_pool(pool, config),
        )
    out_ok = attach_post_open_analysis(
        out_ok,
        plan=sl,
        deposit_usd=sl.effective_deposit_usd,
        settings=fee_settings,
    )
    if out_ok.get("spend_less_cost_analysis"):
        row["spend_less_cost_analysis"] = out_ok["spend_less_cost_analysis"]
    from raydium_lp1.lp_position_economics import (
        build_open_cost_summary,
        failed_attempts_usd_for_pool,
    )

    row["open_economics"] = build_open_cost_summary(
        row,
        sol_price_usd=sol_price_usd,
        failed_attempts_usd=failed_attempts_usd_for_pool(str(pool.get("id") or "")),
    )
    _append_active_position(row)
    out_ok["position"] = row
    return out_ok


def _append_active_position(row: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    if ACTIVE_POSITIONS_PATH.is_file():
        try:
            raw = json.loads(ACTIVE_POSITIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                rows = [dict(x) for x in raw if isinstance(x, dict)]
            elif isinstance(raw, dict):
                rows = [dict(x) for x in (raw.get("positions") or raw.get("open") or []) if isinstance(x, dict)]
        except (OSError, json.JSONDecodeError):
            rows = []
    rows.append(row)
    ACTIVE_POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_POSITIONS_PATH.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
