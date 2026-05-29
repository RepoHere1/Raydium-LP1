from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

from raydium_lp1.live_guard import guard_onchain  # noqa: E402

import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

JUP_ORDER_URL = "https://api.jup.ag/swap/v2/order"
JUP_EXECUTE_URL = "https://api.jup.ag/swap/v2/execute"
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2xzybapC8G4wEGGkZwyTDt1v"


def load_keypair(path: str) -> Keypair:
    p = Path(path).expanduser().resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    return Keypair.from_bytes(bytes(data))


def lamports_from_sol(sol: float) -> int:
    return int(sol * 1_000_000_000)


def main() -> int:
    from raydium_lp1.fee_guard import FeeGuardBlockedError, assert_swap_allowed

    guard_onchain("Jupiter swap (swap_submit.py)")
    keypair_path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    amount_sol = float(os.environ.get("SOLANA_AMOUNT_SOL", "0.001"))
    try:
        assert_swap_allowed(amount_sol)
    except FeeGuardBlockedError as exc:
        raise SystemExit(str(exc)) from exc
    slippage_bps = int(os.environ.get("SOLANA_SLIPPAGE_BPS", "50"))
    jup_api_key = os.environ.get("JUP_API_KEY", "").strip()

    if not keypair_path:
        raise SystemExit("SOLANA_KEYPAIR_PATH is not set")
    if amount_sol <= 0:
        raise SystemExit("SOLANA_AMOUNT_SOL must be > 0")
    if slippage_bps <= 0:
        raise SystemExit("SOLANA_SLIPPAGE_BPS must be > 0")
    if not jup_api_key:
        raise SystemExit("JUP_API_KEY is not set")

    kp = load_keypair(keypair_path)
    amount_lamports = lamports_from_sol(amount_sol)

    headers = {"x-api-key": jup_api_key}
    order_params = {
        "inputMint": SOL_MINT,
        "outputMint": USDC_MINT,
        "amount": amount_lamports,
        "slippageBps": slippage_bps,
    }

    order_resp = requests.get(JUP_ORDER_URL, params=order_params, headers=headers, timeout=20)
    order_resp.raise_for_status()
    order = order_resp.json()

    tx_b64 = order.get("transaction")
    request_id = order.get("requestId")
    last_valid_block_height = order.get("lastValidBlockHeight")

    if not tx_b64 or not request_id:
        raise SystemExit(f"Bad order response: {json.dumps(order, indent=2)}")

    raw_tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))

    signed_tx = VersionedTransaction.populate(
        raw_tx.message,
        [kp.sign_message(raw_tx.message.serialize())],
    )

    signed_b64 = base64.b64encode(bytes(signed_tx)).decode("ascii")

    execute_body = {
        "signedTransaction": signed_b64,
        "requestId": request_id,
    }
    if last_valid_block_height is not None:
        execute_body["lastValidBlockHeight"] = str(last_valid_block_height)

    execute_resp = requests.post(
        JUP_EXECUTE_URL,
        json=execute_body,
        headers={**headers, "Content-Type": "application/json"},
        timeout=30,
    )
    execute_resp.raise_for_status()
    execute = execute_resp.json()

    print(json.dumps({
        "wallet": str(kp.pubkey()),
        "amount_sol": amount_sol,
        "slippage_bps": slippage_bps,
        "requestId": request_id,
        "lastValidBlockHeight": last_valid_block_height,
        "execute": execute,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
