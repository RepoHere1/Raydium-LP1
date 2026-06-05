"""Close all on-chain CLMM positions except pools containing a keep mint (default CARDS)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

DEFAULT_KEEP_MINT = "CARDSccUMFKoPRZxt5vt3ksUbxEFEcnZ3H2pd3dKxYjp"
PAY_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB",
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
}


def main() -> int:
    from raydium_lp1.lp_order_rules import burn_all_empty_clmm_nfts, close_clmm_position
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import _run_script
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-mint", default=DEFAULT_KEEP_MINT, help="Alt mint to keep (pool must include it)")
    parser.add_argument("--preview-only", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    if get_mode() != "live" and not args.preview_only:
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    keep = str(args.keep_mint).strip()
    config = ScannerConfig.from_file(REPO / "config" / "settings.json")
    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    if not chain.get("ok"):
        print(json.dumps(chain, indent=2))
        return 1

    positions = chain.get("positions") or []
    plan_close: list[dict] = []
    plan_keep: list[dict] = []
    pool_cache: dict[str, dict] = {}

    for pos in positions:
        pid = str(pos.get("pool_id") or "")
        nft = str(pos.get("position_nft_mint") or "")
        if not pid or not nft:
            continue
        if pid not in pool_cache:
            try:
                pool_cache[pid] = fetch_pool_by_id(pid, config=config)
            except Exception as exc:
                pool_cache[pid] = {"error": str(exc)}
        pool = pool_cache[pid]
        ma = str(pool.get("mint_a") or "")
        mb = str(pool.get("mint_b") or "")
        pair = f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}"
        row = {"nft": nft, "pool_id": pid, "pair": pair, "liquidity": pos.get("liquidity")}
        if keep in (ma, mb):
            plan_keep.append(row)
        else:
            plan_close.append(row)

    out = {"ok": True, "keep_mint": keep, "keep": plan_keep, "close": plan_close}
    print(json.dumps(out, indent=2))
    if args.preview_only:
        return 0

    from raydium_lp1.fee_guard import reset_session_ledger

    reset_session_ledger()
    results: list[dict] = []
    for item in plan_close:
        nft = item["nft"]
        print(f"\n=== CLOSE {item.get('pair')} nft={nft[:12]}... ===", flush=True)
        try:
            cr = close_clmm_position(nft, timeout=180.0)
        except Exception as exc:
            cr = {"ok": False, "error": str(exc)}
        print(json.dumps(cr, indent=2, default=str))
        results.append({**item, "close": cr})

    # Sweep alt SPL balances → SOL (keep pay mints + CARDS token; skip position NFT receipts)
    sweeps: list[dict] = []
    import importlib.util
    import os
    import subprocess

    swap_script = REPO / "scripts" / "swap_token_to_sol.py"
    try:
        spec = importlib.util.spec_from_file_location("swap_token_to_sol", swap_script)
        swap_mod = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(swap_mod)
        swap_mod._load_dotenv()
        owner = str(swap_mod._load_keypair(swap_mod._keypair_path()).pubkey())
        rpc = swap_mod._rpc_url()
        payload = swap_mod._rpc_post(
            rpc,
            "getTokenAccountsByOwner",
            [owner, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}],
        )
        for acct in (payload.get("value") or []):
            parsed = (acct.get("account") or {}).get("data", {}).get("parsed") or {}
            info = parsed.get("info") or {}
            mint = str(info.get("mint") or "")
            tok = info.get("tokenAmount") or {}
            decimals = int(tok.get("decimals") or 0)
            amount_raw = int(tok.get("amount") or 0)
            if not mint or mint in PAY_MINTS or mint == keep:
                continue
            if decimals == 0 and amount_raw <= 1:
                continue
            if amount_raw <= 0:
                continue
            print(f"\n=== SWAP alt {mint[:12]}... -> SOL ===", flush=True)
            r = subprocess.run(
                [sys.executable, str(swap_script), mint],
                cwd=str(REPO),
                env={**os.environ, "PYTHONPATH": str(REPO / "src")},
                capture_output=True,
                text=True,
                timeout=120,
            )
            sweeps.append({"mint": mint, "ok": r.returncode == 0})
    except Exception as exc:
        sweeps.append({"error": f"sweep pass failed: {exc}"})

    print("\n=== BURN empty position NFTs (liquidity 0) ===", flush=True)
    burn_results = burn_all_empty_clmm_nfts(timeout=180.0)
    for row in burn_results:
        print(json.dumps(row, indent=2, default=str))

    print(
        json.dumps(
            {"closed": results, "burned_empty": burn_results, "sweeps": sweeps, "kept": plan_keep},
            indent=2,
            default=str,
        )
    )
    failed = [x for x in results if not (x.get("close") or {}).get("ok")]
    burn_failed = [x for x in burn_results if not (x.get("burn") or {}).get("ok")]
    return 0 if not failed and not burn_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
