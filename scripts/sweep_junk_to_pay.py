"""Sweep non-pay SPL balances → USDC (preferred) or SOL via Jupiter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB"
KEEP = frozenset({WSOL, USDC, USDT})
ZINC_MINT = "zinc155BS4mSPk8GXQj4R5hkVDQXcW253pTYq5SGyfi"
DUST_RAW = 10_000


def _list_wallet_tokens() -> list[dict]:
    import os
    import urllib.request

    from solders.keypair import Keypair

    from raydium_lp1.scanner import load_dotenv

    load_dotenv()
    kp_path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    rpc = os.environ.get("SOLANA_RPC_URL", "").strip() or "https://api.mainnet-beta.solana.com"
    if not kp_path:
        raise SystemExit("SOLANA_KEYPAIR_PATH not set")
    owner = str(Keypair.from_bytes(bytes(json.loads(Path(kp_path).expanduser().read_text(encoding="utf-8")))).pubkey())

    def rpc_call(method: str, params: list) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload.get("result") or {}

    out: dict[str, dict] = {}
    for program in (
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    ):
        result = rpc_call(
            "getTokenAccountsByOwner",
            [owner, {"programId": program}, {"encoding": "jsonParsed"}],
        )
        for row in result.get("value") or []:
            info = (row.get("account") or {}).get("data", {}).get("parsed", {}).get("info", {})
            mint = str(info.get("mint") or "")
            amt = info.get("tokenAmount") or {}
            raw = int(amt.get("amount") or 0)
            if not mint or raw <= 0:
                continue
            prev = out.get(mint)
            if prev:
                raw += int(prev.get("amount_raw") or 0)
            out[mint] = {
                "mint": mint,
                "amount_raw": raw,
                "decimals": int(amt.get("decimals") or prev.get("decimals") if prev else 0),
            }
    return sorted(out.values(), key=lambda x: -int(x["amount_raw"]))


def _swap_mint(
    input_mint: str,
    *,
    output_mint: str,
    slippage_bps: int,
    max_impact_pct: float,
    dry_run: bool,
) -> dict:
    if dry_run:
        from raydium_lp1.raydium_clmm import quote_sell

        import os
        import urllib.request
        from solders.keypair import Keypair

        from raydium_lp1.scanner import load_dotenv

        load_dotenv()
        kp_path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
        rpc = os.environ.get("SOLANA_RPC_URL", "").strip()
        owner = str(Keypair.from_bytes(bytes(json.loads(Path(kp_path).expanduser().read_text(encoding="utf-8")))).pubkey())

        def bal(m: str) -> int:
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [owner, {"mint": m}, {"encoding": "jsonParsed"}],
                }
            ).encode()
            req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode())
            total = 0
            for acct in (payload.get("result") or {}).get("value") or []:
                info = (acct.get("account") or {}).get("data", {}).get("parsed", {}).get("info", {})
                total += int((info.get("tokenAmount") or {}).get("amount") or 0)
            return total

        amount_raw = bal(input_mint)
        if amount_raw <= DUST_RAW:
            return {"ok": True, "skipped": True, "reason": "dust", "mint": input_mint}
        q = quote_sell(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=amount_raw,
            slippage_bps=slippage_bps,
            max_impact_pct=max_impact_pct,
        )
        return {"ok": q.get("ok"), "mint": input_mint, "amount_raw": str(amount_raw), "quote": q}

    if output_mint == WSOL:
        import subprocess

        cmd = [
            sys.executable,
            str(REPO / "scripts" / "swap_token_to_sol.py"),
            input_mint,
            "--slippage-bps",
            str(slippage_bps),
            "--max-impact-pct",
            str(max_impact_pct),
        ]
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
        lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
        data: dict = {"ok": False, "error": proc.stdout or proc.stderr}
        for ln in reversed(lines):
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if row.get("ok") and row.get("signature"):
                data = row
                break
        if not data.get("ok") and lines:
            try:
                data = json.loads(lines[-1])
            except json.JSONDecodeError:
                pass
        if proc.returncode == 0 and data.get("signature"):
            data["ok"] = True
        data.setdefault("mint", input_mint)
        return data

    from raydium_lp1.emergency import _swap_wallet_alt_to_pay

    sym = "USDC" if output_mint == USDC else "USDT" if output_mint == USDT else "SOL"
    return _swap_wallet_alt_to_pay(
        input_mint,
        output_mint,
        sym,
        max_slippage_pct=slippage_bps / 100.0,
    )


def main() -> int:
    from raydium_lp1.live_guard import guard_onchain
    from raydium_lp1.raydium_clmm import wallet_balance

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pay", choices=("usdc", "sol", "auto"), default="auto")
    parser.add_argument("--slippage-bps", type=int, default=500)
    parser.add_argument("--max-impact-pct", type=float, default=35.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument(
        "--keep-mint",
        action="append",
        default=[],
        help="Do not sweep these mints (e.g. pool alt leg reserved for next LP open)",
    )
    args = parser.parse_args()

    if not args.dry_run:
        guard_onchain("sweep junk tokens to pay leg")

    bal = wallet_balance()
    tokens = _list_wallet_tokens()
    extra_keep = frozenset(args.keep_mint or [])
    junk = [
        t
        for t in tokens
        if t["mint"] not in KEEP
        and t["mint"] not in extra_keep
        and int(t["amount_raw"]) > DUST_RAW
    ]

    prefer_usdc = args.pay in ("usdc", "auto")
    out_mint = USDC if prefer_usdc else WSOL
    out_label = "USDC" if out_mint == USDC else "SOL"

    print(
        json.dumps(
            {
                "wallet": bal.get("address"),
                "sol_balance": bal.get("sol_balance"),
                "usdc_balance": bal.get("usdc_balance"),
                "junk_mints": len(junk),
                "output": out_label,
                "tokens": junk,
            },
            indent=2,
        ),
        flush=True,
    )

    if not junk:
        print(json.dumps({"ok": True, "message": "no junk tokens above dust"}, indent=2))
        return 0

    results: list[dict] = []
    for tok in junk:
        mint = tok["mint"]
        print(f"\n=== sweep {mint[:12]}... -> {out_label} ===", flush=True)
        last: dict = {}
        for attempt in range(1, max(1, args.attempts) + 1):
            last = _swap_mint(
                mint,
                output_mint=out_mint,
                slippage_bps=args.slippage_bps,
                max_impact_pct=args.max_impact_pct,
                dry_run=args.dry_run,
            )
            if last.get("ok") and not last.get("skipped"):
                break
            if last.get("skipped"):
                break
            if out_mint == USDC and attempt == 1 and not args.dry_run:
                out_mint = WSOL
                out_label = "SOL"
                print("  USDC route failed, retrying -> SOL", flush=True)
        print(json.dumps(last, indent=2, default=str))
        results.append({"mint": mint, **last})

    ok = all(r.get("ok") for r in results)
    print(json.dumps({"ok": ok, "sweeps": results}, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
