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


def open_clmm_candidate(
    *,
    pool_id: str | None = None,
    latest_path: Path = DEFAULT_LATEST,
    input_amount_sol: float | None = None,
    tick_lower_pct_below: float = 12.0,
    tick_upper_pct_above: float = 12.0,
    force_pay_token_only: bool | None = None,
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
    report = _read_latest(latest_path)
    pool = _pick_candidate(report, pool_id, config=config)
    pv = pool.get("pool_verification") or {}
    if pv and not pv.get("ok", True):
        return {"ok": False, "error": "pool failed verification", "pool": pool.get("id"), "verification": pv}
    w = wallet_mod.load_wallet()
    cap = assess_capacity(config, w)
    bal_sol = float((cap.get("balance") or {}).get("sol") or 0.0)
    pos_sol = float(input_amount_sol if input_amount_sol is not None else config.position_size_sol)
    reserve = float(config.reserve_sol)
    if bal_sol < reserve + pos_sol + 0.002:
        return {
            "ok": False,
            "error": (
                f"insufficient SOL: balance={bal_sol:.4f} need ~{reserve + pos_sol + 0.002:.4f} "
                "(lower reserve_sol/position_size_sol or fund wallet)"
            ),
            "balance_sol": bal_sol,
        }

    from raydium_lp1.lp_open_style import resolve_live_open_style
    from raydium_lp1.lp_pay_mint import pay_mint_open_error, pay_token_only_enabled, resolve_pay_mint

    lp_style = resolve_live_open_style(config, pool)
    style_open = dict(lp_style.open_kwargs)

    if pay_token_only_enabled(config):
        pay_res = resolve_pay_mint(pool, config)
        if pay_res is None:
            return {"ok": False, "error": pay_mint_open_error(pool, config)}
    else:
        pay_res = resolve_pay_mint(pool, config)

    input_mint = str(style_open.get("input_mint") or (pay_res.pay_mint if pay_res else _sol_mint_for_pool(pool)))

    try:
        fee_est = assert_clmm_open_allowed(pos_sol, settings=config)
    except FeeGuardBlockedError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "fee_guard": True,
            "hint": (
                "CLMM opens need ~0.04+ SOL rent for NFT/tick accounts on top of your deposit. "
                "Fee guard blocks micro-deposits and multi-retry fee burns. "
                "Raise deposit (≥0.008 SOL min) or disable fee_guard_enabled only if you accept the risk."
            ),
        }

    fee_cfg = fee_config_from_settings(config)
    open_kwargs = _build_clmm_open_kwargs(
        style_open,
        pool_id=str(pool["id"]),
        input_mint=input_mint,
        input_amount_human=pos_sol,
        tick_lower_pct_below=tick_lower_pct_below,
        tick_upper_pct_above=tick_upper_pct_above,
    )
    open_kwargs["priority_fee_micro_lamports"] = fee_cfg.max_priority_fee_micro_lamports

    result: dict[str, Any] = {"ok": False, "error": "open not attempted"}
    retry_extras: list[dict[str, Any]] = [{}]
    if fee_cfg.max_open_retries > 1 and style_open.get("single_side"):
        w = float(style_open.get("single_side_width_pct") or lp_style.width_pct)
        retry_extras.append(
            {
                "single_side_width_pct": min(55.0, w * 1.2),
                "band_tick_steps": int(style_open.get("band_tick_steps", 10)) + 4,
            }
        )
    elif fee_cfg.max_open_retries > 1:
        half = float(style_open.get("tick_lower_pct_below") or lp_style.width_pct / 2)
        retry_extras.append(
            {
                "tick_lower_pct_below": min(45.0, half * 1.15),
                "tick_upper_pct_above": min(45.0, half * 1.15),
                "band_tick_steps": int(style_open.get("band_tick_steps", 10)) + 4,
            }
        )

    for extra in retry_extras[: max(1, fee_cfg.max_open_retries)]:
        attempt = {**open_kwargs, **extra}
        result = raydium_clmm.open_position(**attempt)
        if result.get("ok"):
            break
        if result.get("signature") or result.get("tx"):
            break
    if not result.get("ok"):
        err = result.get("error") or (result.get("clmm") or {}).get("confirm_error")
        if err and "Custom" in str(err):
            result["hint"] = (
                "On-chain tx failed (often insufficient SOL for NFT rent + tick accounts). "
                "Keep ~0.04–0.06 SOL in wallet for a 0.005 SOL CLMM open, not just the deposit size."
            )
        out = {"ok": False, "error": err or "CLMM open failed", "clmm": result, "fee_guard_estimate": fee_est}
        return out

    row = {
        "opened_at": _now_iso(),
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "apr": pool.get("apr"),
        "liquidity_usd": pool.get("liquidity_usd"),
        "input_amount_sol": pos_sol,
        "position_nft_mint": result.get("position_nft_mint") or result.get("nftMint"),
        "tx": result.get("tx") or result.get("signature"),
        "clmm_result": result,
        "status": "live_open",
        "momentum": pool.get("momentum"),
        **lp_style.to_position_fields(),
    }
    _append_active_position(row)
    return {"ok": True, "position": row, "clmm": result, "fee_guard_estimate": fee_est}


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
