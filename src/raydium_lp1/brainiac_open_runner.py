"""Shared Brainiac LIVE open + report (wizard, CLI, Cursor scripts)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from raydium_lp1.brainiac_wizard_state import BrainiacWizardAnswers, POOL_PLACEHOLDER, REPO

REPO_ROOT = REPO


@dataclass
class BrainiacOpenRequest:
    pool_id: str
    deposit_usd: float
    fund_non_pay_fraction: float = 0.35
    sol_price_usd: float | None = None
    wide_width_pct: float = 80.0
    min_in_range_factor: float = 0.55
    run_pretrade: bool = True
    pre_live_consensus_scans: int = 5
    pre_live_scan_delay_sec: float = 2.0
    reset_fee_session: bool = False
    skip_fund_swap: bool = False
    skip_settle_after: bool = False

    @classmethod
    def from_wizard(cls, pool_id: str, answers: BrainiacWizardAnswers) -> BrainiacOpenRequest:
        sol_px = float(answers.sol_price_usd) if answers.sol_price_usd > 0 else None
        return cls(
            pool_id=pool_id.strip(),
            deposit_usd=float(answers.deposit_usd),
            fund_non_pay_fraction=float(answers.fund_non_pay_fraction),
            sol_price_usd=sol_px,
            wide_width_pct=float(answers.wide_width_pct),
            min_in_range_factor=float(answers.min_in_range_factor),
            run_pretrade=bool(answers.run_pretrade),
            pre_live_consensus_scans=int(answers.pre_live_consensus_scans),
            pre_live_scan_delay_sec=float(answers.pre_live_scan_delay_sec),
            reset_fee_session=bool(answers.reset_fee_session),
            skip_fund_swap=bool(answers.skip_fund_swap),
            skip_settle_after=bool(answers.skip_settle_after),
        )


def wallet_usd(bal: dict, sol_px: float) -> dict[str, float]:
    sol = float(bal.get("sol_balance") or 0)
    usdc = float(bal.get("usdc_balance") or 0)
    return {
        "sol": sol,
        "usdc": usdc,
        "total_usd": round(sol * sol_px + usdc, 4),
    }


def parse_json_from_process_output(stdout: str, stderr: str = "") -> dict[str, Any]:
    """Parse JSON from subprocess stdout (supports pretty-printed multi-line JSON)."""
    text = (stdout or "").strip()
    if not text:
        return {"ok": False, "error": stderr or "empty stdout"}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return {"ok": False, "error": "no JSON object in stdout", "raw": text[:500]}
    try:
        obj, _end = json.JSONDecoder().raw_decode(text, start)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON parse failed: {exc}", "raw": text[:500]}
    return {"ok": False, "error": "unexpected JSON type"}


def run_pretrade_analysis(pool_id: str, deposit_usd: float) -> dict[str, Any]:
    script = REPO / "scripts" / "_brainiac_pretrade_analysis.py"
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env["BRAINIAC_JSON_COMPACT"] = "1"
    proc = subprocess.run(
        [sys.executable, str(script), pool_id, str(deposit_usd)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        timeout=180,
    )
    if proc.returncode != 0 and not (proc.stdout or "").strip():
        return {
            "ok": False,
            "error": proc.stderr or f"pretrade exit {proc.returncode}",
            "returncode": proc.returncode,
        }
    out = parse_json_from_process_output(proc.stdout or "", proc.stderr or "")
    if not out.get("ok") and proc.returncode != 0:
        out.setdefault("returncode", proc.returncode)
    return out


def apply_brainiac_strategy_settings(*, preview: bool = False) -> dict[str, Any]:
    """Update config/settings.json for Brainiac (Python — avoids PowerShell quote bugs)."""

    strategy_id = "brainiac_cursor_success_80_skewed_no_escrow"
    settings_path = REPO / "config" / "settings.json"
    if not settings_path.is_file():
        return {"ok": False, "error": f"missing {settings_path}"}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = settings_path.with_name(f"settings.json.bak-{stamp}")
    shutil.copy2(settings_path, backup)

    from raydium_lp1.settings_io import read_settings_text, write_settings_json

    raw = read_settings_text(settings_path)
    updated = raw
    updated = re.sub(
        r'"lp_active_strategy"\s*:\s*"[^"]*"',
        f'"lp_active_strategy": "{strategy_id}"',
        updated,
        count=1,
    )
    updated = re.sub(r'"mode"\s*:\s*"[^"]*"', '"mode": "live"', updated, count=1)
    updated = re.sub(r'"dry_run"\s*:\s*(true|false)', '"dry_run": false', updated, count=1)
    if '"lp_sweep_junk_to_pay_leg"' not in updated:
        needle = f'"lp_active_strategy": "{strategy_id}",'
        insert = needle + '\n  "lp_sweep_junk_to_pay_leg": true,'
        if needle in updated:
            updated = updated.replace(needle, insert, 1)

    if preview:
        return {
            "ok": True,
            "preview": True,
            "backup": str(backup),
            "would_set": {
                "lp_active_strategy": strategy_id,
                "mode": "live",
                "dry_run": False,
                "lp_sweep_junk_to_pay_leg": True,
            },
        }

    write_settings_json(settings_path, json.loads(updated))
    return {
        "ok": True,
        "backup": str(backup),
        "settings_path": str(settings_path),
        "lp_active_strategy": strategy_id,
    }


def apply_brainiac_strategy_ps1() -> dict[str, Any]:
    """Deprecated alias — use Python settings patch."""
    return apply_brainiac_strategy_settings()


def _confirm_error_hint(confirm_error: Any) -> str | None:
    raw = str(confirm_error or "")
    if not raw:
        return None
    if "Custom" in raw and ("1" in raw or "6017" in raw):
        return (
            "Raydium rejected the open (insufficient SOL lamports or deposit too small for this band). "
            "Top up to ~0.08 SOL total, try $2–3 deposit, or use a less skewed band."
        )
    return f"On-chain failure: {raw[:200]}"


def _slim_consensus_for_report(consensus: dict[str, Any]) -> dict[str, Any]:
    if not consensus or consensus.get("skipped"):
        return consensus
    return {k: v for k, v in consensus.items() if k not in ("chosen_plan", "chosen_pool")}


def build_plan_for_request(
    pool: dict[str, Any],
    req: BrainiacOpenRequest,
    *,
    fee: dict[str, Any],
    sc: Any,
) -> dict[str, Any]:
    from raydium_lp1.lp_brainiac_cursor_success import build_brainiac_cursor_open_plan

    return build_brainiac_cursor_open_plan(
        pool,
        pool.get("momentum"),
        default_width_pct=req.wide_width_pct,
        settings=fee,
        scanner=sc,
    )


def execute_brainiac_open(req: BrainiacOpenRequest) -> dict[str, Any]:
    """LIVE open with full JSON report."""

    if not req.pool_id or req.pool_id == POOL_PLACEHOLDER:
        return {"ok": False, "error": "pool_id is required (not placeholder)"}

    from raydium_lp1.fee_guard import reset_session_ledger, session_summary
    from raydium_lp1.lp_brainiac_cursor_success import (
        STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        apply_brainiac_fee_and_settlement_settings,
        fee_settings_for_brainiac_procedure,
        fund_non_pay_leg_if_needed,
        open_clmm_with_brainiac_cursor_success,
    )
    from raydium_lp1.lp_junk_to_pay import settlement_policy_for_pool
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import wallet_balance, _run_script
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    load_dotenv()
    if get_mode() != "live":
        return {"ok": False, "error": "mode must be live"}

    pretrade: dict[str, Any] = {}
    if req.run_pretrade:
        pretrade = run_pretrade_analysis(req.pool_id, req.deposit_usd)
        if req.min_in_range_factor > 0:
            ir = float((pretrade.get("placement") or {}).get("in_range_factor") or 0)
            if ir <= 0 and pretrade.get("ok") is False:
                # Pretrade script failed or returned no placement — do not treat as ir=0 block.
                pretrade.setdefault(
                    "warning",
                    "in_range_factor check skipped (pretrade incomplete); consensus/plan still runs",
                )
            elif ir < req.min_in_range_factor:
                return {
                    "ok": False,
                    "error": (
                        f"in_range_factor {ir:.3f} < min {req.min_in_range_factor} "
                        "(wizard block)"
                    ),
                    "pretrade_analysis": pretrade,
                    "hint": "Lower min_in_range_factor in wizard (e.g. 0.50) or pick a pool with higher overlap.",
                }

    sess_before = session_summary()

    if req.reset_fee_session:
        reset_session_ledger()
        sess_before = session_summary()

    sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
    fee = apply_brainiac_fee_and_settlement_settings(fee_settings_for_brainiac_procedure())
    sol_px = float(req.sol_price_usd or fee.get("lp_pay_funding_sol_price_usd") or 180) or 180.0

    pool = fetch_pool_by_id(req.pool_id, config=sc)
    pay = resolve_pay_mint(pool, sc)
    if pay is None:
        return {"ok": False, "error": "pool has no pay-type leg", "pretrade_analysis": pretrade}

    consensus: dict[str, Any] = {"ok": True, "skipped": True}
    if int(req.pre_live_consensus_scans) > 0:
        from raydium_lp1.brainiac_pre_live_consensus import run_pre_live_consensus

        n = int(req.pre_live_consensus_scans)
        print(
            f"\n=== Pre-LIVE consensus: {n} pool refreshes "
            f"({req.pre_live_scan_delay_sec:.0f}s apart) ==="
        )
        consensus = run_pre_live_consensus(
            req.pool_id,
            deposit_usd=req.deposit_usd,
            wide_width_pct=req.wide_width_pct,
            min_in_range_factor=req.min_in_range_factor,
            scan_count=int(req.pre_live_consensus_scans),
            scan_delay_sec=float(req.pre_live_scan_delay_sec),
            config=sc,
            fee_settings=fee,
            sol_price_usd=sol_px,
        )
        if not consensus.get("ok"):
            return {
                "ok": False,
                "error": "pre-LIVE consensus gate blocked open",
                "pretrade_analysis": pretrade,
                "pre_live_consensus": _slim_consensus_for_report(consensus),
                "block_reasons": consensus.get("block_reasons"),
            }
        print(f"  {consensus.get('recommendation')}\n")
        if consensus.get("chosen_pool"):
            pool = consensus["chosen_pool"]
        plan = consensus.get("chosen_plan") or build_plan_for_request(pool, req, fee=fee, sc=sc)
    else:
        plan = build_plan_for_request(pool, req, fee=fee, sc=sc)
    bp = plan.get("brainiac_placement") or {}
    settlement = settlement_policy_for_pool(pool, sc)

    before = wallet_balance()
    w0 = wallet_usd(before, sol_px)

    pay_funding: dict[str, Any] | None = None
    pay_sym = str(pay.pay_symbol or "").upper()
    if pay_sym in ("USDC", "USDT", "USD1"):
        from raydium_lp1.fee_guard import estimate_clmm_open_cost_sol, fee_config_from_settings
        from raydium_lp1.pay_token_funding import ensure_pay_token_for_open

        fund_usd = (
            0.0
            if req.skip_fund_swap
            else float(req.deposit_usd) * float(req.fund_non_pay_fraction)
        )
        usdc_need_human = float(req.deposit_usd) + fund_usd
        fee_cfg = fee_config_from_settings(fee)
        fee_est = estimate_clmm_open_cost_sol(
            fee_cfg,
            deposit_sol=float(req.deposit_usd) / sol_px,
            priority_micro=fee_cfg.max_priority_fee_micro_lamports,
        )
        pay_funding = ensure_pay_token_for_open(
            pay,
            usdc_need_human,
            config=sc,
            fee_settings=fee,
            reserve_sol=float(getattr(sc, "reserve_sol", 0.05) or 0.05),
            open_cost_sol=float(fee_est.get("estimated_total_sol") or 0.02),
            sol_price_usd=sol_px,
        )
        if not pay_funding.get("ok"):
            return {
                "ok": False,
                "error": pay_funding.get("error") or "pay-token (USDC) funding failed",
                "pretrade_analysis": pretrade,
                "pre_live_consensus": _slim_consensus_for_report(consensus),
                "pay_funding": pay_funding,
                "pool_id": req.pool_id,
                "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
            }

    fund = fund_non_pay_leg_if_needed(
        pool,
        target_non_pay_usd=req.deposit_usd * req.fund_non_pay_fraction,
        config=sc,
        sol_price_usd=sol_px,
        user_skip_fund_swap=req.skip_fund_swap,
    )
    if not fund.get("ok"):
        return {
            "ok": False,
            "error": fund.get("error") or "non-pay fund swap failed",
            "fund_non_pay": fund,
            "pay_funding": pay_funding,
            "pretrade_analysis": pretrade,
            "pre_live_consensus": _slim_consensus_for_report(consensus),
            "pool_id": req.pool_id,
            "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        }

    before_open = wallet_balance()
    sol_now = float(before_open.get("sol_balance") or 0)
    reserve_sol = float(getattr(sc, "reserve_sol", 0.05) or 0.05)
    min_sol_open = max(reserve_sol + 0.025, 0.055)
    if sol_now + 1e-9 < min_sol_open:
        return {
            "ok": False,
            "error": (
                f"wallet SOL {sol_now:.4f} too low for CLMM open "
                f"(need ~{min_sol_open:.3f} SOL for rent + tx fees; Custom:1 otherwise)"
            ),
            "hint": "Top up SOL (~0.03–0.05 more), then retry. USDC/GDER legs are ready.",
            "pretrade_analysis": pretrade,
            "pre_live_consensus": _slim_consensus_for_report(consensus),
            "fund_non_pay": fund,
            "pay_funding": pay_funding,
            "pool_id": req.pool_id,
            "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
            "balance_sol": sol_now,
        }

    result = open_clmm_with_brainiac_cursor_success(
        pool_id=req.pool_id,
        input_amount_usd=req.deposit_usd,
        pool=pool,
        fee_guard_settings=fee,
        sol_price_usd=sol_px,
        auto_tune=False,
        skip_fund_swap=req.skip_fund_swap,
        skip_settle_after=req.skip_settle_after,
        wide_width_pct=req.wide_width_pct,
        reset_fee_session=False,
        placement_plan=plan,
    )

    wallet_settlement = result.get("wallet_settlement")

    after = wallet_balance()
    w1 = wallet_usd(after, sol_px)
    wallet_delta = round(w1["total_usd"] - w0["total_usd"], 4)

    chain = _run_script("list_owner_positions.mjs", {}, timeout=90)
    on_chain = [p for p in (chain.get("positions") or []) if str(p.get("pool_id")) == req.pool_id]

    sig = ""
    nft = None
    if result.get("ok"):
        clmm = result.get("clmm") or {}
        sig = str(clmm.get("signature") or clmm.get("txId") or "")
        nft = (result.get("position") or {}).get("position_nft_mint")
    if not sig and on_chain:
        nft = nft or on_chain[-1].get("position_nft_mint")

    sess_end = session_summary()
    spent_sol_run = max(
        0.0,
        float(sess_end.get("spent_sol_est") or 0) - float(sess_before.get("spent_sol_est") or 0),
    )
    network_fee_run_usd = round(spent_sol_run * sol_px, 4)
    opened = bool(result.get("ok")) or bool(on_chain)
    deposit_in_lp = float(req.deposit_usd) if opened else 0.0
    actual_loss_usd = round(max(0.0, -(wallet_delta) - deposit_in_lp), 4)
    network_fee_usd = (
        min(network_fee_run_usd, actual_loss_usd)
        if not opened and actual_loss_usd + 0.0001 < network_fee_run_usd
        else network_fee_run_usd
    )

    if opened:
        loss_interp = (
            f"This run tx fees ~${network_fee_usd:.4f} (ledger). "
            f"~${deposit_in_lp:.2f} in LP (recoverable on close). "
            f"Wallet delta ${wallet_delta:.4f} includes LP + rent + fees."
        )
    else:
        loss_interp = (
            f"Open failed — wallet delta ${wallet_delta:.4f} is your actual USD change. "
            f"This run ledger fees ~${network_fee_usd:.4f} SOL-tx estimate "
            f"(session total ${float(sess_end.get('spent_sol_est') or 0) * sol_px:.2f} "
            f"includes earlier txs if ledger was not reset)."
        )

    report: dict[str, Any] = {
        "pretrade_analysis": pretrade,
        "pre_live_consensus": _slim_consensus_for_report(consensus),
        "ok": opened,
        "pool_id": req.pool_id,
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "strategy": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
        "deposit_usd_requested": req.deposit_usd,
        "wizard_params": {
            "fund_non_pay_fraction": req.fund_non_pay_fraction,
            "wide_width_pct": req.wide_width_pct,
            "min_in_range_factor": req.min_in_range_factor,
            "skip_fund_swap": req.skip_fund_swap,
            "pre_live_consensus_scans": req.pre_live_consensus_scans,
            "pre_live_scan_delay_sec": req.pre_live_scan_delay_sec,
        },
        "pay_type_symbol": pay.pay_symbol,
        "non_pay_symbol": pay.alt_symbol,
        "settlement_policy": settlement,
        "placement": {
            "style": "two-sided wallet_inventory (Brainiac 80% skewed)",
            "skew": plan.get("skew"),
            "tick_lower_pct_below": plan.get("tick_lower_pct_below"),
            "tick_upper_pct_above": plan.get("tick_upper_pct_above"),
            "fee_model_leader": bp.get("fee_model_leader"),
            "theoretical_apr_pct_leader": (bp.get("fee_model_leader") or {}).get("theoretical_apr_pct"),
            "in_range_factor": bp.get("in_range_factor_at_skew"),
        },
        "fund_non_pay": fund,
        "pay_funding": pay_funding,
        "open": {
            "ok": result.get("ok"),
            "error": result.get("error"),
            "clmm_error": (result.get("clmm") or {}).get("error"),
            "confirm_error": (result.get("clmm") or {}).get("confirm_error"),
            "confirm_hint": _confirm_error_hint((result.get("clmm") or {}).get("confirm_error")),
            "signature": sig,
            "nft": nft,
            "wallet_settlement": wallet_settlement or result.get("wallet_settlement"),
        },
        "on_chain_positions": on_chain,
        "fee_session": sess_end,
        "fee_session_this_run": {
            "spent_sol_est": round(spent_sol_run, 6),
            "spent_usd_est": network_fee_run_usd,
            "before_spent_sol": float(sess_before.get("spent_sol_est") or 0),
        },
        "wallet_usd": {
            "sol_price_usd": sol_px,
            "before": w0,
            "after": w1,
            "delta_usd": wallet_delta,
        },
        "permanent_loss_usd": {
            "network_fees_this_run_usd": network_fee_usd,
            "network_fees_ledger_run_usd": network_fee_run_usd,
            "wallet_delta_usd": wallet_delta,
            "actual_wallet_loss_usd": actual_loss_usd,
            "deposit_in_lp_usd": deposit_in_lp,
            "interpretation": loss_interp,
        },
    }
    if result.get("position", {}).get("open_economics"):
        report["open_economics"] = result["position"]["open_economics"]
    return report


def preview_brainiac_open(req: BrainiacOpenRequest) -> dict[str, Any]:
    """Pretrade + plan + optional consensus gate preview (no spend)."""

    from raydium_lp1.brainiac_pre_live_consensus import run_pre_live_consensus
    from raydium_lp1.lp_brainiac_cursor_success import (
        apply_brainiac_fee_and_settlement_settings,
        fee_settings_for_brainiac_procedure,
    )
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    load_dotenv()
    pretrade = run_pretrade_analysis(req.pool_id, req.deposit_usd) if req.run_pretrade else {}
    sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
    fee = apply_brainiac_fee_and_settlement_settings(fee_settings_for_brainiac_procedure())
    sol_px = float(req.sol_price_usd or fee.get("lp_pay_funding_sol_price_usd") or 180) or 180.0
    pool = fetch_pool_by_id(req.pool_id, config=sc)
    pay = resolve_pay_mint(pool, sc)
    consensus: dict[str, Any] = {"ok": True, "skipped": True}
    if int(req.pre_live_consensus_scans) > 0:
        consensus = run_pre_live_consensus(
            req.pool_id,
            deposit_usd=req.deposit_usd,
            wide_width_pct=req.wide_width_pct,
            min_in_range_factor=req.min_in_range_factor,
            scan_count=int(req.pre_live_consensus_scans),
            scan_delay_sec=float(req.pre_live_scan_delay_sec),
            config=sc,
            fee_settings=fee,
            sol_price_usd=sol_px,
        )
        if consensus.get("chosen_plan"):
            plan = consensus["chosen_plan"]
        else:
            plan = build_plan_for_request(pool, req, fee=fee, sc=sc)
    else:
        plan = build_plan_for_request(pool, req, fee=fee, sc=sc)
    return {
        "ok": pay is not None and consensus.get("ok", True),
        "preview_only": True,
        "pool_id": req.pool_id,
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "pay_type": pay.pay_symbol if pay else None,
        "non_pay": pay.alt_symbol if pay else None,
        "pretrade_analysis": pretrade,
        "pre_live_consensus": _slim_consensus_for_report(consensus),
        "placement_plan": {
            "skew": plan.get("skew"),
            "tick_lower_pct_below": plan.get("tick_lower_pct_below"),
            "tick_upper_pct_above": plan.get("tick_upper_pct_above"),
            "brainiac_placement": plan.get("brainiac_placement"),
        },
        "fund_non_pay_would_usd": round(req.deposit_usd * req.fund_non_pay_fraction, 4),
    }
