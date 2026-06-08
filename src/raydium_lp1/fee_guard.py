"""Block and cap Solana / Raydium spend that burns SOL on fees + rent for tiny deposits.

CLMM opens lock **recoverable** position rent (returned on close) plus network fees.
New tick-array rent is paid only when the pool has no array yet (rare on active pools).
Multiple failed retries and high ``priority_fee_micro_lamports`` multiply the damage.
This module is mandatory for every on-chain path in LP1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
SESSION_LEDGER_PATH = REPO / "reports" / "fee_session_ledger.json"

# Lamports → SOL helpers
LAMPORTS_PER_SOL = 1_000_000_000


class FeeGuardBlockedError(RuntimeError):
    """Spend rejected: fees/rent would dominate the trade or session budget exceeded."""


@dataclass(frozen=True)
class FeeGuardConfig:
    enabled: bool = True
    max_priority_fee_micro_lamports: int = 2_000
    jupiter_max_priority_micro_lamports: int = 2_000
    clmm_open_compute_units: int = 200_000
    clmm_close_compute_units: int = 280_000
    clmm_open_rent_sol: float = 0.009
    clmm_close_overhead_sol: float = 0.012
    clmm_base_fee_sol: float = 0.000_02
    min_clmm_deposit_sol: float = 0.17
    min_deposit_to_fee_ratio: float = 4.0
    max_fee_pct_of_deposit: float = 35.0
    max_rent_escrow_pct_of_deposit: float = 50.0
    max_estimated_fee_sol_per_tx: float = 0.065
    max_open_retries: int = 1
    max_session_spend_sol: float = 0.12
    max_session_tx_attempts: int = 4
    block_deposits_below_sol: float = 0.006
    min_lp_deposit_usd: float = 0.25
    sol_price_usd: float = 180.0
    allow_fee_retry_after_failed_tx: bool = False


def fee_config_from_settings(settings: Any | None = None) -> FeeGuardConfig:
    if isinstance(settings, FeeGuardConfig):
        return settings
    if settings is None:
        from raydium_lp1.settings_io import load_settings_json

        settings = load_settings_json(REPO / "config" / "settings.json")
    from raydium_lp1.no_escrow_policy import normalize_settings_no_escrow

    g = normalize_settings_no_escrow(settings if isinstance(settings, dict) else {})

    def _b(key: str, default: bool) -> bool:
        return bool(g.get(key, default))

    def _i(key: str, default: int) -> int:
        return int(g.get(key, default))

    def _f(key: str, default: float) -> float:
        return float(g.get(key, default))

    return FeeGuardConfig(
        enabled=_b("fee_guard_enabled", True),
        max_priority_fee_micro_lamports=max(0, _i("max_priority_fee_micro_lamports", 2_000)),
        jupiter_max_priority_micro_lamports=max(0, _i("jupiter_max_priority_micro_lamports", 2_000)),
        clmm_open_compute_units=max(100_000, _i("clmm_open_compute_units", 200_000)),
        clmm_close_compute_units=max(100_000, _i("clmm_close_compute_units", 280_000)),
        clmm_open_rent_sol=max(0.0, _f("clmm_open_rent_sol", 0.009)),
        clmm_close_overhead_sol=max(0.0, _f("clmm_close_overhead_sol", 0.012)),
        clmm_base_fee_sol=max(0.0, _f("clmm_base_fee_sol", 0.00002)),
        min_clmm_deposit_sol=max(0.0, _f("min_clmm_deposit_sol", 0.008)),
        min_deposit_to_fee_ratio=max(1.0, _f("min_deposit_to_fee_ratio", 4.0)),
        max_fee_pct_of_deposit=max(1.0, _f("max_fee_pct_of_deposit", 35.0)),
        max_rent_escrow_pct_of_deposit=max(1.0, min(100.0, _f("max_rent_escrow_pct_of_deposit", 50.0))),
        max_estimated_fee_sol_per_tx=max(0.0, _f("max_estimated_fee_sol_per_tx", 0.065)),
        max_open_retries=max(1, _i("max_open_retries", 1)),
        max_session_spend_sol=max(0.0, _f("max_session_spend_sol", 0.12)),
        max_session_tx_attempts=max(1, _i("max_session_tx_attempts", 4)),
        block_deposits_below_sol=max(0.0, _f("block_deposits_below_sol", 0.006)),
        min_lp_deposit_usd=max(0.0, _f("min_lp_deposit_usd", 0.25)),
        sol_price_usd=max(1.0, _f("sol_price_usd", _f("lp_pay_funding_sol_price_usd", 180.0))),
        allow_fee_retry_after_failed_tx=_b("allow_fee_retry_after_failed_tx", False),
    )


def priority_fee_sol(micro_lamports: int, compute_units: int) -> float:
    """Priority component: micro-lamports/CU × CU → lamports → SOL."""

    if micro_lamports <= 0 or compute_units <= 0:
        return 0.0
    lamports = (int(micro_lamports) * int(compute_units)) / 1_000_000.0
    return lamports / LAMPORTS_PER_SOL


def cap_priority_micro(requested: int | None, cfg: FeeGuardConfig) -> int:
    if not cfg.enabled:
        return max(0, int(requested or 0))
    req = max(0, int(requested if requested is not None else cfg.max_priority_fee_micro_lamports))
    return min(req, cfg.max_priority_fee_micro_lamports)


def estimate_clmm_open_cost_sol(
    cfg: FeeGuardConfig,
    *,
    deposit_sol: float,
    priority_micro: int | None = None,
) -> dict[str, Any]:
    micro = cap_priority_micro(priority_micro, cfg)
    units = cfg.clmm_open_compute_units
    pri = priority_fee_sol(micro, units)
    recoverable_rent = cfg.clmm_open_rent_sol
    base = cfg.clmm_base_fee_sol
    network_only = pri + base
    total_wallet_sol_need = recoverable_rent + network_only
    pct = (100.0 * network_only / deposit_sol) if deposit_sol > 0 else 999.0
    return {
        "operation": "clmm_open",
        "deposit_sol": round(deposit_sol, 6),
        "priority_micro_lamports": micro,
        "compute_units": units,
        "priority_fee_sol": round(pri, 6),
        "rent_sol": round(recoverable_rent, 6),
        "recoverable_rent_sol": round(recoverable_rent, 6),
        "base_fee_sol": round(base, 6),
        "estimated_total_sol": round(total_wallet_sol_need, 6),
        "network_fee_sol": round(network_only, 6),
        "fee_pct_of_deposit": round(pct, 1),
        "note": "rent_sol is recoverable on close; not burned unless tx fails",
    }


def estimate_clmm_close_cost_sol(cfg: FeeGuardConfig, *, priority_micro: int | None = None) -> dict[str, Any]:
    micro = cap_priority_micro(priority_micro, cfg)
    units = cfg.clmm_close_compute_units
    pri = priority_fee_sol(micro, units)
    overhead = cfg.clmm_close_overhead_sol
    base = cfg.clmm_base_fee_sol
    total = overhead + pri + base
    return {
        "operation": "clmm_close",
        "priority_micro_lamports": micro,
        "compute_units": units,
        "priority_fee_sol": round(pri, 6),
        "overhead_sol": round(overhead, 6),
        "base_fee_sol": round(base, 6),
        "estimated_total_sol": round(total, 6),
    }


def _load_ledger() -> dict[str, Any]:
    if not SESSION_LEDGER_PATH.is_file():
        return {"attempts": [], "spent_sol_est": 0.0}
    try:
        raw = json.loads(SESSION_LEDGER_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except (OSError, json.JSONDecodeError):
        pass
    return {"attempts": [], "spent_sol_est": 0.0}


def _save_ledger(data: dict[str, Any]) -> None:
    SESSION_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_LEDGER_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def record_spend_attempt(operation: str, estimated_sol: float, *, meta: dict[str, Any] | None = None) -> None:
    led = _load_ledger()
    attempts = list(led.get("attempts") or [])
    attempts.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "operation": operation,
            "estimated_sol": round(float(estimated_sol), 6),
            "meta": meta or {},
        }
    )
    led["attempts"] = attempts[-200:]
    led["spent_sol_est"] = round(
        sum(float(a.get("estimated_sol") or 0) for a in led["attempts"]),
        6,
    )
    led["updated_at"] = datetime.now(UTC).isoformat()
    _save_ledger(led)


def session_summary(cfg: FeeGuardConfig | None = None) -> dict[str, Any]:
    cfg = cfg or fee_config_from_settings()
    led = _load_ledger()
    spent = float(led.get("spent_sol_est") or 0)
    attempts = len(led.get("attempts") or [])
    return {
        "enabled": cfg.enabled,
        "spent_sol_est": spent,
        "attempt_count": attempts,
        "max_session_spend_sol": cfg.max_session_spend_sol,
        "max_session_tx_attempts": cfg.max_session_tx_attempts,
        "remaining_sol_budget": round(max(0.0, cfg.max_session_spend_sol - spent), 6),
        "ledger_path": str(SESSION_LEDGER_PATH),
    }


def _check_session_budget(cfg: FeeGuardConfig, estimated_sol: float) -> None:
    if not cfg.enabled:
        return
    led = _load_ledger()
    spent = float(led.get("spent_sol_est") or 0)
    attempts = len(led.get("attempts") or [])
    if attempts >= cfg.max_session_tx_attempts:
        raise FeeGuardBlockedError(
            f"Fee guard: session tx attempt cap ({cfg.max_session_tx_attempts}) reached. "
            f"See {SESSION_LEDGER_PATH}. Fund wallet only after reviewing spend."
        )
    if spent + estimated_sol > cfg.max_session_spend_sol + 1e-9:
        raise FeeGuardBlockedError(
            f"Fee guard: would exceed session spend cap {cfg.max_session_spend_sol:.4f} SOL "
            f"(already ~{spent:.4f} SOL estimated this session)."
        )


def assert_clmm_open_allowed(
    deposit_sol: float,
    *,
    settings: Any | None = None,
    priority_micro: int | None = None,
    open_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Raise if this open is economically unsafe; return cost estimate dict."""

    from raydium_lp1.no_escrow_policy import assert_no_escrow_paid, normalize_settings_no_escrow

    normalized = normalize_settings_no_escrow(settings)
    cfg = fee_config_from_settings(normalized)
    est = estimate_clmm_open_cost_sol(cfg, deposit_sol=deposit_sol, priority_micro=priority_micro)
    rent_est = None
    if open_kwargs is not None:
        from raydium_lp1.lp_rent_escrow import assert_rent_escrow_allowed

        policy_check = assert_no_escrow_paid(
            deposit_sol=deposit_sol,
            open_kwargs=open_kwargs,
            settings=normalized,
            priority_micro=priority_micro,
        )
        rent_est = assert_rent_escrow_allowed(
            deposit_sol=deposit_sol,
            open_kwargs=open_kwargs,
            settings=normalized,
            priority_micro=priority_micro,
        )
        est = {
            **est,
            "rent_escrow": rent_est.to_dict(),
            "no_escrow_policy": policy_check.get("no_escrow_policy"),
        }
    if not cfg.enabled:
        return est

    dep = float(deposit_sol)
    total = float(est["estimated_total_sol"])
    pct = float(est["fee_pct_of_deposit"])
    dep_usd = dep * cfg.sol_price_usd

    if cfg.min_lp_deposit_usd > 0 and dep_usd + 1e-9 < cfg.min_lp_deposit_usd:
        raise FeeGuardBlockedError(
            f"Fee guard: deposit ~${dep_usd:.2f} is below min_lp_deposit_usd "
            f"({cfg.min_lp_deposit_usd:.2f}). Sub-${cfg.min_lp_deposit_usd:.2f} CLMM opens "
            "show tiny notional after failed txs — raise size or close zombies first."
        )

    if dep < cfg.block_deposits_below_sol:
        raise FeeGuardBlockedError(
            f"Fee guard: deposit {dep:.6f} SOL is below block_deposits_below_sol "
            f"({cfg.block_deposits_below_sol}). CLMM rent would eat the wallet — "
            f"raise size or use a CEX, not micro-LP here."
        )
    effective_min = max(
        cfg.min_clmm_deposit_sol,
        total * cfg.min_deposit_to_fee_ratio,
    )
    usd_floor_ok = cfg.min_lp_deposit_usd > 0 and dep_usd + 1e-9 >= cfg.min_lp_deposit_usd
    if not usd_floor_ok and dep < effective_min:
        raise FeeGuardBlockedError(
            f"Fee guard: deposit {dep:.4f} SOL is too small. Need ≥ {effective_min:.4f} SOL "
            f"(min_clmm={cfg.min_clmm_deposit_sol}, est. cost ~{total:.4f} SOL incl. ~{cfg.clmm_open_rent_sol:.4f} rent). "
            "Micro LP opens are how wallets get fee-drained on Solana."
        )
    if total > cfg.max_estimated_fee_sol_per_tx:
        raise FeeGuardBlockedError(
            f"Fee guard: estimated tx cost {total:.4f} SOL exceeds "
            f"max_estimated_fee_sol_per_tx {cfg.max_estimated_fee_sol_per_tx}."
        )
    # Network fees vs deposit; recoverable rent is not a burn.
    if dep >= cfg.clmm_open_rent_sol * 2 and pct > cfg.max_fee_pct_of_deposit:
        raise FeeGuardBlockedError(
            f"Fee guard: fees+rent would be ~{pct:.0f}% of deposit "
            f"(max {cfg.max_fee_pct_of_deposit:.0f}%). "
            f"Est. {total:.4f} SOL cost on {dep:.4f} SOL deposit — increase size or lower rent settings."
        )

    _check_session_budget(cfg, total)
    return est


def assert_clmm_close_allowed(*, settings: Any | None = None, priority_micro: int | None = None) -> dict[str, Any]:
    cfg = fee_config_from_settings(settings)
    est = estimate_clmm_close_cost_sol(cfg, priority_micro=priority_micro)
    if cfg.enabled:
        total = float(est["estimated_total_sol"])
        if total > cfg.max_estimated_fee_sol_per_tx:
            raise FeeGuardBlockedError(
                f"Fee guard: estimated close cost {total:.4f} SOL too high."
            )
        _check_session_budget(cfg, total)
    return est


def sanitize_clmm_payload(script_name: str, payload: dict[str, Any], *, settings: Any | None = None) -> dict[str, Any]:
    """Cap priority fees and inject compute unit limits before Node runs."""

    cfg = fee_config_from_settings(settings)
    out = dict(payload)
    if not cfg.enabled:
        return out

    micro = cap_priority_micro(out.get("priority_fee_micro_lamports"), cfg)
    out["priority_fee_micro_lamports"] = micro
    out["fee_guard_applied"] = True

    if script_name == "open_position.mjs":
        out["compute_units"] = cfg.clmm_open_compute_units
        dep = float(out.get("input_amount_human") or 0)
        open_kw = {
            k: out[k]
            for k in (
                "full_range",
                "wide_range",
                "wide_range_width_pct",
                "literal_pool_full_range",
                "single_side",
                "single_side_width_pct",
                "tick_lower_pct_below",
                "tick_upper_pct_above",
            )
            if k in out
        }
        assert_clmm_open_allowed(dep, settings=settings, priority_micro=micro, open_kwargs=open_kw or None)
    elif script_name in ("close_position.mjs", "burn_position_nft.mjs", "harvest_clmm_fees.mjs"):
        out["compute_units"] = cfg.clmm_close_compute_units if script_name != "harvest_clmm_fees.mjs" else 200_000
        assert_clmm_close_allowed(settings=settings, priority_micro=micro)
        if script_name in ("close_position.mjs", "harvest_clmm_fees.mjs"):
            out["jupiter_priority_micro_lamports"] = min(
                cfg.jupiter_max_priority_micro_lamports,
                int(out.get("jupiter_priority_micro_lamports") or cfg.jupiter_max_priority_micro_lamports),
            )
    elif script_name == "swap_sol_to_pay.mjs":
        from raydium_lp1.routes import WSOL_MINT

        inp_mint = str(out.get("input_mint") or WSOL_MINT)
        if inp_mint == WSOL_MINT:
            lamports = int(out.get("amount_lamports") or out.get("amount_raw") or 0)
            assert_swap_allowed(lamports / 1_000_000_000, settings=settings)
        else:
            assert_jupiter_token_swap_allowed(settings=settings)
        out["jupiter_priority_micro_lamports"] = min(
            cfg.jupiter_max_priority_micro_lamports,
            int(out.get("jupiter_priority_micro_lamports") or cfg.jupiter_max_priority_micro_lamports),
        )

    return out


def guard_onchain_fee(operation: str, **context: Any) -> dict[str, Any] | None:
    """Called from live_guard after mode check. Optional context: deposit_sol, script_name."""

    cfg = fee_config_from_settings()
    if not cfg.enabled:
        return None

    script = str(context.get("script_name") or "")
    dep = context.get("deposit_sol")
    if dep is not None and ("open" in operation.lower() or script == "open_position.mjs"):
        return assert_clmm_open_allowed(
            float(dep),
            settings=context.get("settings"),
            priority_micro=context.get("priority_micro"),
            open_kwargs=context.get("open_kwargs"),
        )
    if script == "swap_sol_to_pay.mjs" or "swap" in operation.lower():
        from raydium_lp1.routes import WSOL_MINT

        inp_mint = str(context.get("input_mint") or WSOL_MINT)
        if inp_mint != WSOL_MINT:
            assert_jupiter_token_swap_allowed(settings=context.get("settings"))
        elif dep is not None:
            assert_swap_allowed(float(dep), settings=context.get("settings"))
        else:
            _check_session_budget(cfg, cfg.clmm_base_fee_sol * 2)
        return None
    if (
        "close" in operation.lower()
        or script in ("close_position.mjs", "harvest_clmm_fees.mjs")
        or "harvest" in operation.lower()
    ):
        return assert_clmm_close_allowed(priority_micro=context.get("priority_micro"))
    _check_session_budget(cfg, cfg.clmm_base_fee_sol)
    return None


def reset_session_ledger() -> dict[str, Any]:
    """Clear session spend counters (after reviewing ledger or starting fresh)."""

    data = {"attempts": [], "spent_sol_est": 0.0, "updated_at": datetime.now(UTC).isoformat()}
    _save_ledger(data)
    return session_summary()


def note_broadcast_result(script_name: str, result: dict[str, Any], estimate: dict[str, Any] | None) -> None:
    """Record spend only after a confirmed successful on-chain tx."""

    if not result.get("ok"):
        return
    if result.get("confirm_error"):
        return
    if result.get("confirmed") is False:
        return
    sig = (
        result.get("signature")
        or result.get("tx")
        or result.get("txId")
        or result.get("harvest_signature")
    )
    if not sig:
        return
    est_sol = float((estimate or {}).get("estimated_total_sol") or 0)
    if est_sol <= 0:
        cfg = fee_config_from_settings()
        if script_name == "open_position.mjs":
            est_sol = float(estimate_clmm_open_cost_sol(cfg, deposit_sol=0)["estimated_total_sol"])
        else:
            est_sol = float(estimate_clmm_close_cost_sol(cfg)["estimated_total_sol"])
    record_spend_attempt(script_name, est_sol, meta={"ok": bool(result.get("ok")), "sig": result.get("signature")})


def fee_guard_readiness_blockers(settings: Any | None = None) -> list[str]:
    cfg = fee_config_from_settings(settings)
    if not cfg.enabled:
        return []
    out: list[str] = []
    sess = session_summary(cfg)
    if sess["attempt_count"] >= cfg.max_session_tx_attempts:
        out.append(
            f"fee guard: session tx cap hit ({sess['attempt_count']}/{cfg.max_session_tx_attempts})"
        )
    if float(sess["spent_sol_est"]) >= cfg.max_session_spend_sol * 0.95:
        out.append(
            f"fee guard: session spend ~{sess['spent_sol_est']:.4f} SOL "
            f"(cap {cfg.max_session_spend_sol})"
        )
    return out


def assert_jupiter_token_swap_allowed(*, settings: Any | None = None) -> None:
    """USDC/USDT/etc → alt Jupiter swaps: only network fee + session cap (not SOL min size)."""

    cfg = fee_config_from_settings(settings)
    if not cfg.enabled:
        return
    _check_session_budget(cfg, cfg.clmm_base_fee_sol * 2)


def assert_swap_allowed(amount_sol: float, *, settings: Any | None = None) -> None:
    cfg = fee_config_from_settings(settings)
    if not cfg.enabled:
        return
    if float(amount_sol) < cfg.block_deposits_below_sol:
        raise FeeGuardBlockedError(
            f"Fee guard: swap amount {amount_sol:.6f} SOL below minimum {cfg.block_deposits_below_sol}."
        )
    _check_session_budget(cfg, cfg.clmm_base_fee_sol * 2)


def assert_transfer_allowed(lamports: int, *, settings: Any | None = None) -> None:
    cfg = fee_config_from_settings(settings)
    if not cfg.enabled:
        return
    sol = lamports / LAMPORTS_PER_SOL
    if sol < cfg.block_deposits_below_sol:
        raise FeeGuardBlockedError(f"Fee guard: transfer {sol:.6f} SOL too small to justify network cost.")
    _check_session_budget(cfg, cfg.clmm_base_fee_sol)
