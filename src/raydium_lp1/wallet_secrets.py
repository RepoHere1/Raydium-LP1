"""Sync wallet fields between ``.env`` and ``config/settings.json`` (local only)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_ENV_PATH = REPO / ".env"
DEFAULT_SETTINGS_PATH = REPO / "config" / "settings.json"

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,88}$")


def _validate_address(address: str) -> None:
    if not address or not _BASE58_RE.match(address.strip()):
        raise ValueError(f"invalid Solana address: {address[:12]!r}...")


def read_env_file(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env_file(updates: dict[str, str], path: Path = DEFAULT_ENV_PATH) -> None:
    lines: list[str] = []
    existing = read_env_file(path) if path.is_file() else {}
    merged = {**existing, **{k: v for k, v in updates.items() if v is not None}}
    keys_written: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=", 1)[0].strip()
                if key in merged:
                    lines.append(f"{key}={merged[key]}")
                    keys_written.add(key)
                    continue
            lines.append(line)
    for key, val in merged.items():
        if key not in keys_written:
            lines.append(f"{key}={val}")
    if not lines or not any(l.strip() for l in lines):
        lines = ["# Raydium-LP1 local secrets", ""]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def sync_wallet_to_settings(address: str, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    from raydium_lp1.settings_io import load_settings_json, write_settings_json

    _validate_address(address)
    data = load_settings_json(path) if path.is_file() else {}
    data["wallet_address"] = address.strip()
    write_settings_json(path, data)


def sync_wallet_both(
    *,
    address: str,
    private_key: str = "",
    keypair_path: str = "",
    env_path: Path = DEFAULT_ENV_PATH,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> dict[str, str]:
    """Write wallet to ``.env`` and ``config/settings.json``."""

    _validate_address(address)
    env_updates: dict[str, str] = {"WALLET_ADDRESS": address.strip()}
    if private_key:
        env_updates["WALLET_PRIVATE_KEY"] = private_key.strip()
    if keypair_path:
        env_updates["SOLANA_KEYPAIR_PATH"] = keypair_path.strip()
    write_env_file(env_updates, env_path)
    for key, val in env_updates.items():
        os.environ[key] = val
    sync_wallet_to_settings(address, settings_path)
    return env_updates


def pubkey_from_keypair_file(path: str) -> str:
    from solders.keypair import Keypair

    kp = _keypair_from_file(path)
    return str(kp.pubkey())


def _keypair_from_file(path: str) -> "Keypair":
    from solders.keypair import Keypair

    p = Path(path).expanduser().resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"keypair file must be a JSON byte array: {p}")
    secret = bytes(int(x) for x in data)
    return Keypair.from_bytes(secret)


def _keypair_from_private_key_material(raw: str) -> "Keypair":
    from solders.keypair import Keypair

    s = raw.strip()
    if not s:
        raise ValueError("empty private key material")
    if s.startswith("["):
        arr = json.loads(s)
        if not isinstance(arr, list):
            raise ValueError("private key JSON must be a byte array")
        return Keypair.from_bytes(bytes(int(x) for x in arr))
    return Keypair.from_base58_string(s)


def export_signer_keypair_file(
    *,
    out_path: Path | None = None,
    env_path: Path = DEFAULT_ENV_PATH,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> dict[str, str]:
    """Write Solana CLI-style keypair JSON from ``WALLET_PRIVATE_KEY`` and fix ``.env``."""

    from raydium_lp1.scanner import load_dotenv

    load_dotenv()
    pk = (os.environ.get("WALLET_PRIVATE_KEY") or "").strip()
    if not pk:
        raise ValueError(
            "WALLET_PRIVATE_KEY missing in .env — paste your key via import_wallet.ps1 first"
        )
    kp = _keypair_from_private_key_material(pk)
    address = str(kp.pubkey())
    target = (out_path or (REPO / "secrets" / "lp1_signer.json")).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    secret = list(bytes(kp))
    target.write_text(json.dumps(secret) + "\n", encoding="utf-8")
    sync_wallet_both(
        address=address,
        keypair_path=str(target),
        env_path=env_path,
        settings_path=settings_path,
    )
    return {"address": address, "keypair_path": str(target)}
