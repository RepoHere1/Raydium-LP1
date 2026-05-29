from __future__ import annotations

import json
import os
from pathlib import Path

from solders.keypair import Keypair


def resolve_keypair_path() -> Path:
    path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    if not path:
        raise SystemExit("SOLANA_KEYPAIR_PATH is not set")
    if path.startswith("~"):
        path = str(Path(path).expanduser())
    return Path(path).resolve()


def load_keypair(path: Path) -> Keypair:
    raw = path.read_text(encoding="utf-8").strip()
    data = json.loads(raw)
    if not isinstance(data, list):
        raise SystemExit(f"Keypair file must contain a JSON array: {path}")
    secret = bytes(data)
    if len(secret) not in (64, 32):
        raise SystemExit(f"Unexpected key length in {path}: {len(secret)}")
    return Keypair.from_bytes(secret)


def main() -> int:
    keypair_path = resolve_keypair_path()
    kp = load_keypair(keypair_path)
    print(json.dumps({
        "keypair_path": str(keypair_path),
        "public_key": str(kp.pubkey()),
        "ok": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())