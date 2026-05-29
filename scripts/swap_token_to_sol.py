"""Swap any SPL token balance → SOL via Jupiter (LIVE, fee-capped)."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

WSOL_MINT = "So11111111111111111111111111111111111111112"
JUP_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP = "https://lite-api.jup.ag/swap/v1/swap"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://jup.ag",
}


def _load_dotenv() -> None:
    from raydium_lp1.scanner import load_dotenv

    load_dotenv()


def _rpc_url() -> str:
    return (
        os.environ.get("SOLANA_RPC_URL", "").strip()
        or (json.loads((REPO / "config" / "settings.json").read_text(encoding="utf-8")).get("solana_rpc_urls") or ["https://api.mainnet-beta.solana.com"])[0]
    )


def _keypair_path() -> str:
    p = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    if not p:
        raise SystemExit("SOLANA_KEYPAIR_PATH not set in .env")
    return str(Path(p).expanduser())


def _load_keypair(path: str):
    from solders.keypair import Keypair

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Keypair.from_bytes(bytes(data))


def _rpc_post(url: str, method: str, params: list) -> dict:
    import urllib.request

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload.get("result") or {}


def _wallet_pubkey(kp) -> str:
    return str(kp.pubkey())


def _token_balance_raw(rpc: str, owner: str, mint: str) -> tuple[int, int]:
    """Return (amount_raw, decimals)."""

    result = _rpc_post(
        rpc,
        "getTokenAccountsByOwner",
        [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
    )
    accounts = result.get("value") or []
    total = 0
    decimals = 0
    for row in accounts:
        info = (row.get("account") or {}).get("data") or {}
        parsed = info.get("parsed") if isinstance(info, dict) else None
        if not isinstance(parsed, dict):
            continue
        token = parsed.get("info") or {}
        amt = token.get("tokenAmount") or {}
        total += int(amt.get("amount") or 0)
        decimals = int(amt.get("decimals") or decimals or 0)
    return total, decimals


def _jupiter_quote(*, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int) -> dict:
    import urllib.parse
    import urllib.request

    qs = urllib.parse.urlencode(
        {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
            "slippageBps": str(slippage_bps),
            "swapMode": "ExactIn",
        }
    )
    req = urllib.request.Request(f"{JUP_QUOTE}?{qs}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _jupiter_swap_tx(*, quote: dict, user_pubkey: str, priority_micro: int) -> str:
    import urllib.request

    body = json.dumps(
        {
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "asLegacyTransaction": False,
            "computeUnitPriceMicroLamports": priority_micro,
        }
    ).encode()
    req = urllib.request.Request(
        JUP_SWAP,
        data=body,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read().decode())
    tx = payload.get("swapTransaction")
    if not tx:
        raise RuntimeError(f"Jupiter swap build failed: {payload}")
    return tx


def _send_signed_tx(rpc: str, signed_b64: str) -> str:
    result = _rpc_post(rpc, "sendTransaction", [signed_b64, {"encoding": "base64", "skipPreflight": False}])
    if isinstance(result, str):
        return result
    raise RuntimeError(f"sendTransaction failed: {result}")


def main() -> int:
    from raydium_lp1.fee_guard import cap_priority_micro, fee_config_from_settings, record_spend_attempt
    from raydium_lp1.live_guard import guard_onchain
    from raydium_lp1.raydium_clmm import quote_sell
    from solders.transaction import VersionedTransaction

    parser = argparse.ArgumentParser(description="Swap token mint → SOL (Jupiter, full wallet balance).")
    parser.add_argument("input_mint", help="SPL mint to sell (e.g. pump token)")
    parser.add_argument("--amount-raw", type=int, default=0, help="Raw token units; 0 = entire balance")
    parser.add_argument("--slippage-bps", type=int, default=300, help="Slippage bps (default 300 = 3%%)")
    parser.add_argument("--max-impact-pct", type=float, default=30.0, help="Block if Jupiter impact above this")
    parser.add_argument("--preview-only", action="store_true", help="Quote only; do not sign")
    args = parser.parse_args()

    input_mint = args.input_mint.strip()
    if input_mint == WSOL_MINT:
        raise SystemExit("input mint is already WSOL — nothing to swap")

    _load_dotenv()
    if not args.preview_only:
        guard_onchain(f"Jupiter token→SOL swap ({input_mint[:8]}…)")

    kp_path = _keypair_path()
    kp = _load_keypair(kp_path)
    owner = _wallet_pubkey(kp)
    rpc = _rpc_url()

    bal_raw, decimals = _token_balance_raw(rpc, owner, input_mint)
    amount_raw = int(args.amount_raw) if args.amount_raw > 0 else bal_raw
    if amount_raw <= 0:
        print(json.dumps({"ok": False, "error": "zero token balance for this mint", "mint": input_mint, "wallet": owner}, indent=2))
        return 1

    probe = quote_sell(
        input_mint=input_mint,
        output_mint=WSOL_MINT,
        amount_raw=amount_raw,
        slippage_bps=args.slippage_bps,
        max_impact_pct=args.max_impact_pct,
    )
    plan = {
        "ok": True,
        "wallet": owner,
        "input_mint": input_mint,
        "output_mint": WSOL_MINT,
        "amount_raw": str(amount_raw),
        "decimals": decimals,
        "quote": probe,
    }
    if not probe.get("ok"):
        plan["ok"] = False
        plan["error"] = probe.get("error") or "quote failed"
        print(json.dumps(plan, indent=2))
        return 1
    if probe.get("verdict") == "high_impact":
        plan["ok"] = False
        plan["error"] = f"price impact {float(probe.get('price_impact_pct') or 0)*100:.2f}% exceeds max {args.max_impact_pct}%"
        print(json.dumps(plan, indent=2))
        return 1
    if probe.get("verdict") == "no_route":
        plan["ok"] = False
        plan["error"] = "no Jupiter route to SOL for this mint/size"
        print(json.dumps(plan, indent=2))
        return 1

    print(json.dumps({"plan": plan}, indent=2))
    if args.preview_only:
        return 0

    fee_cfg = fee_config_from_settings()
    pri = cap_priority_micro(None, fee_cfg)
    quote = _jupiter_quote(
        input_mint=input_mint,
        output_mint=WSOL_MINT,
        amount_raw=amount_raw,
        slippage_bps=args.slippage_bps,
    )
    tx_b64 = _jupiter_swap_tx(quote=quote, user_pubkey=owner, priority_micro=pri)
    raw_tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    signed = VersionedTransaction.populate(raw_tx.message, [kp.sign_message(raw_tx.message.serialize())])
    sig = _send_signed_tx(rpc, base64.b64encode(bytes(signed)).decode())

    record_spend_attempt(
        "jupiter_token_to_sol",
        fee_cfg.clmm_base_fee_sol * 2,
        meta={"mint": input_mint, "signature": sig},
    )
    print(
        json.dumps(
            {
                "ok": True,
                "signature": sig,
                "input_mint": input_mint,
                "amount_raw": str(amount_raw),
                "out_amount_quote": quote.get("outAmount"),
                "priority_micro_lamports": pri,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
