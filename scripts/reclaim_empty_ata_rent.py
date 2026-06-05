"""Close zero-balance SPL token accounts and reclaim rent → native SOL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    from raydium_lp1.live_guard import guard_onchain
    from raydium_lp1.raydium_clmm import _run_script, wallet_balance
    from raydium_lp1.scanner import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--keep-mint", action="append", default=[], help="Extra mints to keep open")
    args = parser.parse_args()

    load_dotenv()
    if not args.preview_only:
        guard_onchain("reclaim empty token account rent")
        from raydium_lp1.fee_guard import reset_session_ledger

        reset_session_ledger()

    before = wallet_balance()
    payload = {"preview_only": bool(args.preview_only), "keep_mints": list(args.keep_mint or [])}
    out = _run_script("close_empty_token_accounts.mjs", payload, timeout=120.0)
    out["wallet_before"] = {
        "sol_balance": before.get("sol_balance"),
        "usdc_balance": before.get("usdc_balance"),
    }
    if not args.preview_only and out.get("ok"):
        out["wallet_after"] = wallet_balance()
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
