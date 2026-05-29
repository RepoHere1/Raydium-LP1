from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

from raydium_lp1.live_guard import guard_onchain  # noqa: E402

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.hash import Hash
from solana.rpc.api import Client
from solana.rpc.types import TxOpts


def load_keypair(path: str) -> Keypair:
    p = Path(path).expanduser().resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    return Keypair.from_bytes(bytes(data))


def main() -> int:
    guard_onchain("SOL transfer (trade_submit.py)")
    keypair_path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    if not keypair_path:
        raise SystemExit("SOLANA_KEYPAIR_PATH is not set")

    rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()
    recipient = os.environ.get("SOLANA_RECIPIENT", "").strip()
    lamports = int(os.environ.get("SOLANA_LAMPORTS", "1000"))

    if not recipient:
        raise SystemExit("SOLANA_RECIPIENT is not set")
    if lamports <= 0:
        raise SystemExit("SOLANA_LAMPORTS must be > 0")

    kp = load_keypair(keypair_path)
    client = Client(rpc_url)

    latest = client.get_latest_blockhash().value.blockhash
    bh = Hash.from_string(str(latest))

    ix = transfer(
        TransferParams(
            from_pubkey=kp.pubkey(),
            to_pubkey=Pubkey.from_string(recipient),
            lamports=lamports,
        )
    )

    tx = Transaction.new_signed_with_payer(
        [ix],
        kp.pubkey(),
        [kp],
        bh,
    )

    resp = client.send_transaction(
        tx,
        opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed"),
    )

    print(json.dumps({
        "wallet": str(kp.pubkey()),
        "keypair_path": keypair_path,
        "rpc_url": rpc_url,
        "recipient": recipient,
        "lamports": lamports,
        "sent": True,
        "response": str(resp),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
