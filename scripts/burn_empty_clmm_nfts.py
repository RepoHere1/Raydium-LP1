"""Burn all zero-liquidity CLMM position NFTs (removes Raydium $0 ghost rows)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    from raydium_lp1.lp_order_rules import burn_all_empty_clmm_nfts
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import _run_script
    from raydium_lp1.scanner import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-only", action="store_true", help="List NFTs that would be burned")
    args = parser.parse_args()

    load_dotenv()
    if get_mode() != "live" and not args.preview_only:
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    if not chain.get("ok"):
        print(json.dumps(chain, indent=2))
        return 1

    ghosts = [
        p
        for p in (chain.get("positions") or [])
        if int(p.get("liquidity") or 0) == 0
    ]
    if args.preview_only:
        print(json.dumps({"ok": True, "would_burn": ghosts, "count": len(ghosts)}, indent=2))
        return 0

    from raydium_lp1.fee_guard import reset_session_ledger

    reset_session_ledger()
    results = burn_all_empty_clmm_nfts(positions=chain.get("positions") or [], timeout=180.0)
    print(json.dumps({"ok": True, "burned": results}, indent=2, default=str))
    failed = [r for r in results if not (r.get("burn") or {}).get("ok")]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
