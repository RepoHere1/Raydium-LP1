#!/usr/bin/env python3
"""Break down where wallet SOL is (native vs token-account rent vs LP positions)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

WSOL = "So11111111111111111111111111111111111111112"


def main() -> int:
    from raydium_lp1.raydium_clmm import _run_script, wallet_balance
    from raydium_lp1.scanner import load_dotenv

    load_dotenv()
    rpc = os.environ.get("SOLANA_RPC_URL", "").strip()
    wb = wallet_balance()
    owner = str(wb.get("address") or "")

    def rpc_call(method: str, params: list) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        return payload.get("result") or {}

    acc = rpc_call("getAccountInfo", [owner, {"encoding": "jsonParsed"}])
    native_lamports = int((acc.get("value") or {}).get("lamports") or 0)

    token_rows: list[dict] = []
    rent_lamports = 0
    for program in (
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    ):
        result = rpc_call(
            "getTokenAccountsByOwner",
            [owner, {"programId": program}, {"encoding": "jsonParsed"}],
        )
        for row in result.get("value") or []:
            acct = row.get("account") or {}
            lam = int(acct.get("lamports") or 0)
            rent_lamports += lam
            info = acct.get("data", {}).get("parsed", {}).get("info", {})
            mint = str(info.get("mint") or "")
            amt = int((info.get("tokenAmount") or {}).get("amount") or 0)
            dec = int((info.get("tokenAmount") or {}).get("decimals") or 0)
            token_rows.append(
                {
                    "pubkey": row.get("pubkey"),
                    "mint": mint,
                    "amount_raw": amt,
                    "decimals": dec,
                    "account_lamports": lam,
                    "account_sol": lam / 1e9,
                    "is_wsol": mint == WSOL,
                    "likely_nft": amt == 1 and dec == 0,
                }
            )

    chain = _run_script("list_owner_positions.mjs", {}, timeout=90)
    positions = chain.get("positions") or []
    sol_price = 200.0  # rough for USD hints

    out = {
        "ok": True,
        "address": owner,
        "native_sol": native_lamports / 1e9,
        "wallet_balance_sol": wb.get("sol_balance"),
        "usdc": wb.get("usdc_balance"),
        "token_account_rent_sol": rent_lamports / 1e9,
        "token_account_rent_usd_approx": (rent_lamports / 1e9) * sol_price,
        "token_accounts": token_rows,
        "clmm_positions": positions,
        "position_count": len(positions),
        "recoverable_rent_hint_sol_per_position": 0.0075,
        "recoverable_rent_hint_total_sol": 0.0075 * len(positions),
        "recoverable_rent_hint_total_usd_approx": 0.0075 * len(positions) * sol_price,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
