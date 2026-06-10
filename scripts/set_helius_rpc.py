#!/usr/bin/env python3
"""Set Helius as primary Solana RPC in .env and config/settings.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raydium_lp1 import pool_verify  # noqa: E402
from raydium_lp1.settings_io import load_settings_json, write_settings_json  # noqa: E402

FALLBACKS = (
    "https://solana-rpc.publicnode.com",
    "https://solana.drpc.org",
    "https://api.mainnet-beta.solana.com",
)


def helius_url(api_key: str) -> str:
    key = api_key.strip()
    if key.startswith("http"):
        return key
    return f"https://mainnet.helius-rpc.com/?api-key={key}"


def patch_env(env_path: Path, primary: str) -> None:
    fb = ",".join(FALLBACKS)
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()

    def set_kv(key: str, value: str) -> None:
        nonlocal lines
        found = False
        out: list[str] = []
        for line in lines:
            if re.match(rf"^\s*{re.escape(key)}\s*=", line):
                out.append(f"{key}={value}")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"{key}={value}")
        lines = out

    set_kv("RAYDIUM_API_BASE", "https://api-v3.raydium.io")
    set_kv("SOLANA_RPC_URL", primary)
    set_kv("SOLANA_RPC_URLS", fb)
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def patch_settings(settings_path: Path, urls: list[str]) -> None:
    data = load_settings_json(settings_path)
    clean = pool_verify.filter_rpc_urls(urls, warn=True) or [pool_verify.DEFAULT_PUBLIC_RPC]
    data["solana_rpc_urls"] = clean
    write_settings_json(settings_path, data)
    print(f"Updated {settings_path} with {len(clean)} RPC URL(s).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Helius RPC for LIVE trading")
    parser.add_argument("api_key", help="Helius API key or full https://mainnet.helius-rpc.com/?api-key=... URL")
    parser.add_argument("--settings", type=Path, default=ROOT / "config" / "settings.json")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    args = parser.parse_args()

    primary = helius_url(args.api_key)
    urls = [primary, *FALLBACKS]
    patch_env(args.env, primary)
    print(f"Wrote {args.env} (SOLANA_RPC_URL=Helius)")

    if args.settings.is_file():
        patch_settings(args.settings, urls)
    else:
        print(f"No {args.settings}; .env alone is enough for CLMM scripts.", file=sys.stderr)

    print(json.dumps({"ok": True, "primary_rpc": primary[:60] + "..." if len(primary) > 60 else primary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
