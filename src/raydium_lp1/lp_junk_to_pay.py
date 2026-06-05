"""Pay-type settlement: pool-agnostic pay leg vs non-pay leg (any symbol name).

- **Pay-type** — resolved per pool via ``resolve_pay_mint`` (SOL / USDC / USDT).
  Sweeps consolidate *into* pay-type; inventory funding swaps *from* pay-type only.
- **Non-pay (junker) token** — the other side of the pair (whatever it is called).
  Never a sweep sink, never a swap input for funding. Not hardcoded to any ticker.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from raydium_lp1.pay_token_catalog import pay_token_spec
from raydium_lp1.routes import WSOL_MINT

REPO = Path(__file__).resolve().parents[2]

STABLE_MINTS = frozenset(
    {
        WSOL_MINT,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB",
        "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
    }
)


def _norm_symbol(sym: str) -> str:
    s = (sym or "").strip().upper()
    return "SOL" if s == "WSOL" else s


def junk_sweep_to_pay_enabled(config: Any | None) -> bool:
    if config is None:
        return True
    return bool(getattr(config, "lp_sweep_junk_to_pay_leg", True))


def pool_pair_mints(pool: Mapping[str, Any]) -> frozenset[str]:
    out: set[str] = set()
    for key in ("mint_a", "mint_b"):
        m = str(pool.get(key) or "").strip()
        if m:
            out.add(m)
    return frozenset(out)


def pay_mints_resolved(pay: Any) -> frozenset[str]:
    out: set[str] = {str(pay.pay_mint)}
    if _norm_symbol(str(pay.pay_symbol)) in ("SOL", "WSOL"):
        out.add(WSOL_MINT)
    return frozenset(out)


def non_pay_mints_for_pool(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> frozenset[str]:
    """Pair mints that are not the resolved pay-type (junker / memecoin side — any name)."""

    from raydium_lp1.lp_pay_mint import resolve_pay_mint

    pair = pool_pair_mints(pool)
    pay = resolve_pay_mint(pool, config)
    if pay is None:
        return pair
    return frozenset(m for m in pair if m not in pay_mints_resolved(pay))


def junker_mints_for_pool(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> frozenset[str]:
    """Alias: non-pay pool mints (legacy name)."""

    return non_pay_mints_for_pool(pool, config)


def non_pay_symbol_for_pool(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> str | None:
    from raydium_lp1.lp_pay_mint import resolve_pay_mint

    pay = resolve_pay_mint(pool, config)
    if pay is None:
        return None
    return str(pay.alt_symbol or "").strip() or None


def mint_is_non_pay(mint: str, pool: Mapping[str, Any], config: Any | None = None) -> bool:
    return str(mint or "").strip() in non_pay_mints_for_pool(pool, config)


mint_is_junker = mint_is_non_pay


def resolve_pay_output_for_pool(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> tuple[str, str] | None:
    """Mint + symbol for junk sweeps / close trash — always pay-type."""

    from raydium_lp1.lp_pay_mint import resolve_pay_mint

    pay = resolve_pay_mint(pool, config)
    if pay is None:
        return None

    pay_mint = pay.pay_mint
    if pay.pay_symbol.upper() in ("SOL", "WSOL"):
        pay_mint = WSOL_MINT
    if pay_mint in non_pay_mints_for_pool(pool, config):
        return None
    return pay_mint, pay.pay_symbol


def keep_mints_for_pool(
    pool: Mapping[str, Any],
    config: Any | None = None,
    *,
    extra: frozenset[str] | None = None,
) -> frozenset[str]:
    """Retain pay-type, both pair legs, and stables during sweeps."""

    from raydium_lp1.lp_pay_mint import resolve_pay_mint

    keep = set(STABLE_MINTS)
    keep.update(pool_pair_mints(pool))
    pay = resolve_pay_mint(pool, config)
    if pay is not None:
        keep.update(pay_mints_resolved(pay))
    sweep_out = resolve_pay_output_for_pool(pool, config)
    if sweep_out is not None:
        keep.add(sweep_out[0])
    if extra:
        keep.update(extra)
    return frozenset(keep)


def settlement_policy_for_pool(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    """Runtime policy snapshot for dashboards / order-type plans."""

    from raydium_lp1.lp_pay_mint import resolve_pay_mint

    pay = resolve_pay_mint(pool, config)
    pay_out = resolve_pay_output_for_pool(pool, config)
    return {
        "pay_type_symbol": pay.pay_symbol if pay else None,
        "pay_type_mint": pay_out[0] if pay_out else None,
        "non_pay_symbol": non_pay_symbol_for_pool(pool, config),
        "non_pay_mints": sorted(non_pay_mints_for_pool(pool, config)),
        "sweep_to_pay_type": junk_sweep_to_pay_enabled(config),
        "fund_from_pay_type_only": True,
    }


def sweep_junk_to_pay_leg(
    *,
    pool: Mapping[str, Any] | None = None,
    config: Any | None = None,
    keep_mints: frozenset[str] | None = None,
    slippage_bps: int = 800,
    max_impact_pct: float = 40.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    if pool is None:
        return _sweep_via_script(
            pay_flag="sol",
            keep=keep_mints or frozenset(),
            slippage_bps=slippage_bps,
            max_impact_pct=max_impact_pct,
            dry_run=dry_run,
        )

    pay_out = resolve_pay_output_for_pool(pool, config)
    if pay_out is None:
        return {"ok": False, "error": "no pay-type mint for junk sweep"}
    pay_mint, pay_sym = pay_out
    keep = keep_mints or keep_mints_for_pool(pool, config)
    pay_flag = (
        "usdc"
        if pay_sym.upper() == "USDC"
        else "sol"
        if pay_sym.upper() in ("SOL", "WSOL")
        else "auto"
    )
    payload = _sweep_via_script(
        pay_flag=pay_flag,
        keep=keep,
        slippage_bps=slippage_bps,
        max_impact_pct=max_impact_pct,
        dry_run=dry_run,
    )
    payload["pay_output_mint"] = pay_mint
    payload["pay_output_symbol"] = pay_sym
    payload["non_pay_mints"] = sorted(non_pay_mints_for_pool(pool, config))
    return payload


def _sweep_via_script(
    *,
    pay_flag: str,
    keep: frozenset[str],
    slippage_bps: int,
    max_impact_pct: float,
    dry_run: bool,
) -> dict[str, Any]:
    script = REPO / "scripts" / "sweep_junk_to_pay.py"
    cmd = [
        sys.executable,
        str(script),
        "--pay",
        pay_flag,
        "--slippage-bps",
        str(slippage_bps),
        "--max-impact-pct",
        str(max_impact_pct),
        "--attempts",
        "2",
    ]
    if dry_run:
        cmd.append("--dry-run")
    for m in sorted(keep):
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


def get_wallet_mint_balance_raw(mint: str) -> int:
    """Sum SPL/Token-2022 balance for one mint in the signer wallet (no solders dep)."""

    import urllib.request

    from raydium_lp1.raydium_clmm import wallet_balance

    mint = str(mint or "").strip()
    if not mint:
        return 0
    import os

    from raydium_lp1.scanner import load_dotenv

    load_dotenv()
    rpc = os.environ.get("SOLANA_RPC_URL", "").strip() or "https://api.mainnet-beta.solana.com"
    wb = wallet_balance(timeout=25.0)
    owner = str(wb.get("address") or "").strip() if wb.get("ok") else ""
    if not owner:
        return 0

    def rpc_call(method: str, params: list) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload.get("result") or {}

    total = 0
    for program in (
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    ):
        result = rpc_call(
            "getTokenAccountsByOwner",
            [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
        )
        for row in result.get("value") or []:
            info = (row.get("account") or {}).get("data", {}).get("parsed", {}).get("info", {})
            amt = info.get("tokenAmount") or {}
            total += int(amt.get("amount") or 0)
    return total


def estimate_mint_value_usd(
    mint: str,
    *,
    amount_raw: int,
    sol_price_usd: float = 180.0,
) -> float:
    """Jupiter quote mint -> USDC (fallback SOL) for USD notional."""

    from raydium_lp1.raydium_clmm import quote_sell

    raw = max(0, int(amount_raw))
    if raw <= 0:
        return 0.0
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    q = quote_sell(input_mint=mint, output_mint=usdc, amount_raw=raw, slippage_bps=200)
    if q.get("ok") and q.get("out_amount"):
        return int(q["out_amount"]) / 1_000_000.0
    q2 = quote_sell(input_mint=mint, output_mint=WSOL_MINT, amount_raw=raw, slippage_bps=200)
    if q2.get("ok") and q2.get("out_amount"):
        return (int(q2["out_amount"]) / 1_000_000_000.0) * float(sol_price_usd)
    return 0.0


def non_pay_wallet_inventory_usd(
    pool: Mapping[str, Any],
    config: Any | None = None,
    *,
    sol_price_usd: float = 180.0,
) -> dict[str, Any]:
    """Non-pay (junker) leg balance in wallet, USD estimate via Jupiter."""

    from raydium_lp1.lp_pay_mint import resolve_pay_mint

    pay = resolve_pay_mint(pool, config)
    if pay is None:
        return {"ok": False, "usd": 0.0, "amount_raw": 0, "symbol": None}
    mint = str(pay.alt_mint or "").strip()
    sym = str(pay.alt_symbol or "").strip()
    raw = get_wallet_mint_balance_raw(mint) if mint else 0
    usd = estimate_mint_value_usd(mint, amount_raw=raw, sol_price_usd=sol_price_usd) if mint else 0.0
    return {
        "ok": True,
        "mint": mint,
        "symbol": sym,
        "amount_raw": raw,
        "usd": round(usd, 4),
    }


def fund_non_pay_leg_from_pay_mint(
    pool: Mapping[str, Any],
    *,
    target_non_pay_usd: float,
    sol_price_usd: float = 180.0,
    slippage_bps: int = 250,
    config: Any | None = None,
) -> dict[str, Any]:
    """Swap pay-type → non-pay pair leg only (never non-pay as input)."""

    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.raydium_clmm import swap_tokens

    pay = resolve_pay_mint(pool, config)
    if pay is None:
        return {"ok": False, "error": "no pay leg"}

    non_pay_mint = str(pay.alt_mint or "").strip()
    non_pay_sym = str(pay.alt_symbol or "").strip()
    if not non_pay_mint:
        return {"ok": False, "error": "no non-pay mint on pair"}

    pay_sym = pay.pay_symbol.upper()
    pay_mint = pay.pay_mint if pay_sym not in ("SOL", "WSOL") else WSOL_MINT

    if pay_mint in non_pay_mints_for_pool(pool, config):
        return {"ok": False, "error": "pay-type mint classified as non-pay; check pool metadata"}

    if pay_sym in ("SOL", "WSOL"):
        lamports = int(
            max(5_000_000, (float(target_non_pay_usd) / sol_price_usd) * 1e9 * 1.15)
        )
        sw = swap_tokens(
            input_mint=WSOL_MINT,
            output_mint=non_pay_mint,
            amount_raw=lamports,
            slippage_bps=slippage_bps,
        )
        return {
            "ok": bool(sw.get("ok")),
            "direction": f"pay({pay_sym})→non_pay({non_pay_sym})",
            "pay_mint": pay_mint,
            "non_pay_mint": non_pay_mint,
            "non_pay_symbol": non_pay_sym,
            "signature": sw.get("signature"),
            "error": sw.get("error"),
        }

    spec_pay = pay_token_spec(pay_sym)
    if spec_pay is None:
        return {"ok": False, "error": f"unsupported pay {pay_sym}"}

    pay_human = float(target_non_pay_usd) * 1.08
    pay_raw = int(math.ceil(pay_human * (10 ** spec_pay.decimals)))
    from raydium_lp1.raydium_clmm import wallet_balance

    bal = wallet_balance(timeout=20.0)
    have_raw = int(float(bal.get(f"{pay_sym.lower()}_balance") or 0) * (10 ** spec_pay.decimals))
    if have_raw + 1 < pay_raw:
        pay_raw = max(1, have_raw - 1)
    if pay_raw <= 0:
        return {
            "ok": False,
            "error": f"insufficient {pay_sym} for non-pay fund swap (have ~${have_raw / 10 ** spec_pay.decimals:.4f})",
            "direction": f"pay({pay_sym})→non_pay({non_pay_sym})",
        }
    sw = swap_tokens(
        input_mint=spec_pay.mint,
        output_mint=non_pay_mint,
        amount_raw=pay_raw,
        slippage_bps=max(slippage_bps, 1500),
    )
    return {
        "ok": bool(sw.get("ok")),
        "direction": f"pay({pay_sym})→non_pay({non_pay_sym})",
        "pay_mint": spec_pay.mint,
        "non_pay_mint": non_pay_mint,
        "non_pay_symbol": non_pay_sym,
        "signature": sw.get("signature"),
        "error": sw.get("error"),
    }


def fund_alt_from_pay_mint(
    pool: Mapping[str, Any],
    *,
    target_alt_usd: float,
    sol_price_usd: float = 180.0,
    slippage_bps: int = 250,
    config: Any | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for ``fund_non_pay_leg_from_pay_mint``."""

    return fund_non_pay_leg_from_pay_mint(
        pool,
        target_non_pay_usd=target_alt_usd,
        sol_price_usd=sol_price_usd,
        slippage_bps=slippage_bps,
        config=config,
    )


def close_position_pay_trash_options(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    """close_position.mjs: trash → pay-type, keep pair + pay mints."""

    pay_out = resolve_pay_output_for_pool(pool, config)
    if pay_out is None:
        return {"sweep_trash_to_sol": False}
    pay_mint, _ = pay_out
    keep = keep_mints_for_pool(pool, config)
    return {
        "sweep_trash_to_sol": True,
        "trash_output_mint": pay_mint,
        "trash_keep_mints": sorted(keep),
    }
