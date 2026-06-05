"""Post-trade wallet hygiene: fund pay tokens from SOL, sweep junk alts → SOL."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parent.parent.parent
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB"
KEEP = frozenset({WSOL, USDC, USDT})


def sweep_junk_to_sol(
    *,
    slippage_bps: int = 800,
    max_impact_pct: float = 40.0,
    dry_run: bool = False,
    keep_mints: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Swap every non-pay SPL balance above dust to SOL via Jupiter."""

    script = REPO / "scripts" / "sweep_junk_to_pay.py"
    cmd = [
        sys.executable,
        str(script),
        "--pay",
        "sol",
        "--slippage-bps",
        str(slippage_bps),
        "--max-impact-pct",
        str(max_impact_pct),
        "--attempts",
        "2",
    ]
    if dry_run:
        cmd.append("--dry-run")
    for m in sorted(keep_mints or ()):
        cmd.extend(["--keep-mint", m])
    proc = subprocess.run(
        cmd,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={**dict(__import__("os").environ), "PYTHONPATH": str(REPO / "src")},
    )
    try:
        lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
        payload = json.loads(lines[-1]) if lines else {"ok": proc.returncode == 0, "raw": proc.stdout}
        if not payload.get("ok") and (proc.stdout or "").find('"signature"') >= 0:
            for ln in reversed(lines):
                try:
                    row = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if row.get("ok") and row.get("signature"):
                    payload = row
                    break
    except json.JSONDecodeError:
        payload = {"ok": False, "error": proc.stdout or proc.stderr, "returncode": proc.returncode}
    payload["returncode"] = proc.returncode
    if proc.returncode == 0 and not payload.get("ok") and payload.get("signature"):
        payload["ok"] = True
    return payload


def fund_usdc_from_sol_if_needed(
    target_usdc: float,
    *,
    reserve_sol: float = 0.06,
    open_cost_sol: float = 0.042,
    sol_price_usd: float | None = None,
    fee_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Raise USDC balance toward target by swapping SOL when pay-token funding is enabled."""

    from raydium_lp1.lp_pay_mint import PayMintResolution
    from raydium_lp1.pay_token_funding import ensure_pay_token_for_open
    from raydium_lp1.scanner import ScannerConfig

    config = ScannerConfig.from_file(REPO / "config" / "settings.json")
    pay_res = PayMintResolution(
        pay_mint=USDC,
        pay_symbol="USDC",
        alt_mint="zinc155BS4mSPk8GXQj4R5hkVDQXcW253pTYq5SGyfi",
        alt_symbol="ZINC",
        pay_is_mint_a=False,
    )
    return ensure_pay_token_for_open(
        pay_res,
        float(target_usdc),
        config=config,
        fee_settings=fee_settings,
        reserve_sol=reserve_sol,
        open_cost_sol=open_cost_sol,
        sol_price_usd=sol_price_usd,
    )


def settle_wallet_after_trade(
    *,
    pool: Mapping[str, Any] | None = None,
    config: Any | None = None,
    fund_usdc_target: float | None = None,
    sol_price_usd: float | None = None,
    fee_settings: dict[str, Any] | None = None,
    keep_mints: frozenset[str] | None = None,
    sweep_junk: bool = True,
) -> dict[str, Any]:
    """After LP trade: optional stable top-up; sweep junk → pay leg (never sweep pay/alt as junk)."""

    from raydium_lp1.raydium_clmm import wallet_balance

    out: dict[str, Any] = {"ok": True}
    if fund_usdc_target is not None and fund_usdc_target > 0:
        out["usdc_funding"] = fund_usdc_from_sol_if_needed(
            fund_usdc_target,
            sol_price_usd=sol_price_usd,
            fee_settings=fee_settings,
        )
        if not out["usdc_funding"].get("ok"):
            out["ok"] = False
    if sweep_junk:
        from raydium_lp1.lp_junk_to_pay import junk_sweep_to_pay_enabled, sweep_junk_to_pay_leg

        if pool is not None and junk_sweep_to_pay_enabled(config):
            out["junk_sweep"] = sweep_junk_to_pay_leg(
                pool=pool,
                config=config,
                keep_mints=keep_mints,
            )
        else:
            out["junk_sweep"] = sweep_junk_to_sol(keep_mints=keep_mints)
    else:
        out["junk_sweep"] = {"ok": True, "skipped": True}
    if not out["junk_sweep"].get("ok") and out["junk_sweep"].get("sweeps"):
        failed = [s for s in out["junk_sweep"]["sweeps"] if not s.get("ok")]
        if failed:
            out["ok"] = False
    out["balance"] = wallet_balance()
    return out
