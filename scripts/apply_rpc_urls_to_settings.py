#!/usr/bin/env python3
"""Merge validated RPC URLs from a JSON file into config/settings.json (optional)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raydium_lp1 import pool_verify  # noqa: E402
from raydium_lp1.settings_io import load_settings_json, write_settings_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply solana_rpc_urls (+ optional raydium_api_base) to settings.json")
    parser.add_argument("--settings", type=Path, default=Path("config/settings.json"))
    parser.add_argument("--urls-json", type=Path, required=True, help="JSON array of URL strings")
    parser.add_argument("--raydium-api-base", type=str, default="", help="If set, overwrite raydium_api_base")
    args = parser.parse_args()

    if not args.settings.exists():
        print(f"No {args.settings}; skipped.", file=sys.stderr)
        return 0

    raw_urls = json.loads(args.urls_json.read_text(encoding="utf-8"))
    if not isinstance(raw_urls, list):
        print("--urls-json must contain a JSON array", file=sys.stderr)
        return 2

    data = load_settings_json(args.settings)
    clean = pool_verify.filter_rpc_urls([str(u) for u in raw_urls], warn=True) or [pool_verify.DEFAULT_PUBLIC_RPC]
    data["solana_rpc_urls"] = clean
    base = (args.raydium_api_base or "").strip()
    if base:
        data["raydium_api_base"] = base
    write_settings_json(args.settings, data)
    print(f"Updated {args.settings} with {len(clean)} RPC URL(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
