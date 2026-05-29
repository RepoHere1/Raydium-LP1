from __future__ import annotations

import json
import os
from pathlib import Path

from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from solana.rpc.api import Client


def load_keypair(path: str) -> Keypair:
    p = Path(path).expanduser().resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    return Keypair.from_bytes(bytes(data))


def build_dummy_transfer(fee_payer: Pubkey) -> Transaction:
    rpc = Client(os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"))
    latest = rpc.get_latest_blockhash().value.blockhash
    bh = Hash.from_string(str(latest))
    msg = Message.new_with_blockhash([], fee_payer, bh)
    return Transaction.new_unsigned(msg)


def main() -> int:
    keypair_path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    if not keypair_path:
        raise SystemExit("SOLANA_KEYPAIR_PATH is not set")

    kp = load_keypair(keypair_path)
    rpc = Client(os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"))

    latest = rpc.get_latest_blockhash().value.blockhash
    bh = Hash.from_string(str(latest))

    tx = Transaction.new_unsigned(
        Message.new_with_blockhash([], kp.pubkey(), bh)
    )

    # Exact signing call site:
    tx.sign([kp], bh)

    # Exact live-send call site:
    # sig = rpc.send_transaction(tx, kp)

    print(json.dumps({
        "wallet": str(kp.pubkey()),
        "keypair_path": keypair_path,
        "signed": True,
        "send_call": "rpc.send_transaction(tx, kp)",
        "note": "This skeleton signs a no-op transaction; add real instructions before sending.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())