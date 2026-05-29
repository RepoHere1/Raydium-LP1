"""
raydium_clmm — Python facade over the Node bridge in raydium_clmm_node/.

Spawns small Node ESM scripts via subprocess.run, passing JSON on stdin,
parsing JSON from stdout. Keeps the Python side stdlib-only (in spirit —
this file uses os + subprocess + json only) while letting the official
@raydium-io/raydium-sdk-v2 do the heavy lifting in Node.

Public functions:
    open_position(pool_id, input_mint, input_amount_human,
                  tick_lower_pct_below=10, tick_upper_pct_above=10,
                  slippage_bps=100, priority_fee_micro_lamports=50_000) -> dict
    close_position(position_nft_mint, slippage_bps=100, keep_position=False,
                   priority_fee_micro_lamports=50_000) -> dict
    quote_sell(input_mint, output_mint, amount_raw,
               slippage_bps=100, max_impact_pct=5.0) -> dict
    wallet_balance() -> dict   # SOL + USDC + WSOL snapshot, no spend
    status() -> dict           # health check (node found? deps installed? RPC reachable?)

Failure modes are returned as {"ok": False, "error": "..."} not raised.

Reads from .env (or process env):
    SOLANA_RPC_URL         — required for open/close
    SOLANA_KEYPAIR_PATH    — required for open/close (Solana CLI JSON-array file)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO  = Path(__file__).parent.parent.parent.resolve()        # src/raydium_lp1/ → repo root
NODE_DIR = REPO / "src" / "raydium_lp1" / "raydium_clmm_node"
_ONCHAIN_SPEND_SCRIPTS = frozenset({"open_position.mjs", "close_position.mjs"})


def _load_env() -> dict:
    """Read .env without depending on python-dotenv."""
    env = {}
    p = REPO / ".env"
    if not p.exists():
        return env
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def _node_binary() -> str | None:
    """Return absolute path to node, or None if missing."""
    return shutil.which("node")


def _run_script(script_name: str, payload: dict, timeout: float = 60.0) -> dict:
    """Spawn a Node script, send JSON on stdin, parse JSON on stdout."""
    if script_name in _ONCHAIN_SPEND_SCRIPTS:
        from raydium_lp1.live_guard import guard_onchain

        try:
            guard_onchain(f"Raydium CLMM {script_name}")
        except Exception as exc:
            return {"ok": False, "error": str(exc), "mode_blocked": True}

    node = _node_binary()
    if not node:
        return {"ok": False, "error": "node not found on PATH; install Node.js 18+ from nodejs.org"}

    script = NODE_DIR / script_name
    if not script.exists():
        return {"ok": False, "error": f"node script missing: {script}"}

    # Inject env-derived defaults
    env = _load_env()
    payload = dict(payload)  # don't mutate caller
    payload.setdefault("rpc_url",      env.get("SOLANA_RPC_URL", ""))
    payload.setdefault("keypair_path", env.get("SOLANA_KEYPAIR_PATH", ""))

    try:
        proc = subprocess.run(
            # v0.2 — --dns-result-order=ipv4first defeats Node 24's IPv6
            # preference which makes Jupiter/Helius fetch hang from US ISPs.
            [node, "--dns-result-order=ipv4first", str(script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(NODE_DIR),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{script_name} timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "error": f"subprocess failed: {type(exc).__name__}: {exc}"}

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()

    if not out:
        return {"ok": False,
                "error": f"{script_name} produced no stdout; rc={proc.returncode}",
                "stderr": err[:500]}

    # Last non-empty line is our JSON result (Node may have printed warnings before)
    json_line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("{")), "")
    if not json_line:
        return {"ok": False, "error": f"{script_name} output not JSON: {out[:300]}", "stderr": err[:200]}

    try:
        result = json.loads(json_line)
    except Exception as exc:
        return {"ok": False, "error": f"{script_name} JSON parse failed: {exc}; raw={json_line[:300]}"}

    # Surface stderr noise on failure for debugging
    if not result.get("ok") and err:
        result.setdefault("stderr", err[:400])
    return result


# ---- public API ---------------------------------------------------------

def open_position(*,
                  pool_id: str,
                  input_mint: str,
                  input_amount_human: float,
                  tick_lower_pct_below: float = 10.0,
                  tick_upper_pct_above: float = 10.0,
                  slippage_bps: int = 100,
                  priority_fee_micro_lamports: int = 50_000,
                  single_side: str | None = None,         # v0.3 — "above" | "below" | None
                  single_side_start_pct: float = 0.5,     # band starts this % away from spot
                  single_side_width_pct: float = 15.0,     # band is this wide
                  band_tick_steps: int = 10,
                  min_tick_steps: int = 2,
                  timeout: float = 90.0) -> dict:
    """Open a new CLMM position.

    single_side="above": band ENTIRELY above current price → input ONLY in
                         mintA side (SOL in a SOL/USDC pool). No USDC needed.
    single_side="below": band ENTIRELY below current price → input ONLY in
                         mintB side (USDC in a SOL/USDC pool). No SOL needed.
    single_side=None:    standard straddling band → both tokens needed.
    """
    return _run_script("open_position.mjs", {
        "pool_id":                    pool_id,
        "input_mint":                 input_mint,
        "input_amount_human":         float(input_amount_human),
        "tick_lower_pct_below":       float(tick_lower_pct_below),
        "tick_upper_pct_above":       float(tick_upper_pct_above),
        "single_side":                single_side,
        "single_side_start_pct":      float(single_side_start_pct),
        "single_side_width_pct":      float(single_side_width_pct),
        "band_tick_steps":            int(band_tick_steps),
        "min_tick_steps":             int(min_tick_steps),
        "slippage_bps":               int(slippage_bps),
        "priority_fee_micro_lamports":int(priority_fee_micro_lamports),
    }, timeout=timeout)


def close_position(*,
                   position_nft_mint: str,
                   slippage_bps: int = 100,
                   keep_position: bool = False,
                   payout_as: str | None = None,   # v0.3 — None | "SOL" | "USDC"
                   priority_fee_micro_lamports: int = 50_000,
                   timeout: float = 120.0) -> dict:
    """Close (decrease to 0 + collect + burn NFT) a CLMM position.

    payout_as="SOL": after the close confirms, auto-swap any received
                     non-SOL token (e.g. USDC) back to SOL via Jupiter so you
                     never get stuck with dust tokens. Two on-chain txs total.
    payout_as=None:  return whatever the band held (default).
    """
    return _run_script("close_position.mjs", {
        "position_nft_mint":          position_nft_mint,
        "slippage_bps":               int(slippage_bps),
        "keep_position":              bool(keep_position),
        "payout_as":                  payout_as,
        "priority_fee_micro_lamports":int(priority_fee_micro_lamports),
    }, timeout=timeout)


def quote_sell(*,
               input_mint: str,
               output_mint: str,
               amount_raw: int | str,
               slippage_bps: int = 100,
               max_impact_pct: float = 5.0,
               timeout: float = 20.0) -> dict:
    """Probe Jupiter for a sell quote at FULL position size. The anti-slippage
    defense. verdict will be 'ok' | 'high_impact' | 'no_route'."""
    return _run_script("quote_sell.mjs", {
        "input_mint":     input_mint,
        "output_mint":    output_mint,
        "amount":         str(amount_raw),
        "slippage_bps":   int(slippage_bps),
        "max_impact_pct": float(max_impact_pct),
    }, timeout=timeout)


def wallet_balance(timeout: float = 20.0) -> dict:
    """Read-only snapshot of the bot wallet's SOL + USDC + WSOL balance,
    plus current Solana block height. Spends nothing. Use this before any
    open_position() to verify funds are present.

    Returns:
      {ok: true, address, sol_balance, usdc_balance, wsol_balance,
       lamports, rpc_url (masked), block_height}
      OR {ok: false, error: "..."}
    """
    return _run_script("balance.mjs", {}, timeout=timeout)


def status() -> dict:
    """Health snapshot: node, deps, env keys."""
    env = _load_env()
    node = _node_binary()
    pkg_json = NODE_DIR / "package.json"
    node_modules = NODE_DIR / "node_modules"
    return {
        "module":                "raydium_clmm",
        "node_binary":           node,
        "node_dir":              str(NODE_DIR),
        "package_json_present":  pkg_json.exists(),
        "node_modules_present":  node_modules.exists(),
        "rpc_url_set":           bool(env.get("SOLANA_RPC_URL")),
        "keypair_path_set":      bool(env.get("SOLANA_KEYPAIR_PATH")),
        "keypair_file_exists":   bool(env.get("SOLANA_KEYPAIR_PATH")
                                      and Path(env["SOLANA_KEYPAIR_PATH"]).expanduser().exists()),
    }


if __name__ == "__main__":
    import sys
    s = status()
    print(json.dumps(s, indent=2))
    missing = []
    if not s["node_binary"]:          missing.append("Node.js 18+ on PATH")
    if not s["package_json_present"]: missing.append(f"package.json in {NODE_DIR}")
    if not s["node_modules_present"]: missing.append(f"`npm install` in {NODE_DIR}")
    if not s["rpc_url_set"]:          missing.append("SOLANA_RPC_URL in .env")
    if not s["keypair_path_set"]:     missing.append("SOLANA_KEYPAIR_PATH in .env")
    elif not s["keypair_file_exists"]:missing.append(f"keypair file at {(_load_env() or {}).get('SOLANA_KEYPAIR_PATH')}")
    if missing:
        print("\nMISSING:")
        for m in missing: print(f"  - {m}")
        sys.exit(1)
    print("\nAll prereqs present.")
