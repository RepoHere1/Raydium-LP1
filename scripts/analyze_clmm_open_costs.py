"""Analyze CLMM open costs from live_executor result JSON or a signature."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    from raydium_lp1.lp_tx_cost_analysis import analyze_open_bundle, analyze_transaction
    from raydium_lp1.scanner import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-json", type=Path, help="open_clmm_candidate result file")
    parser.add_argument("--signature", default="", help="Single tx signature")
    parser.add_argument("--deposit-usd", type=float, default=None)
    args = parser.parse_args()

    load_dotenv()
    import os

    rpc = os.environ.get("SOLANA_RPC_URL", "").strip() or "https://api.mainnet-beta.solana.com"
    from solders.keypair import Keypair

    kp_path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    if not kp_path:
        raise SystemExit("SOLANA_KEYPAIR_PATH not set")
    wallet = str(Keypair.from_bytes(bytes(json.loads(Path(kp_path).expanduser().read_text()))).pubkey())

    if args.signature:
        row = analyze_transaction(args.signature, wallet=wallet, rpc_url=rpc)
        print(json.dumps(row.to_dict(), indent=2))
        return 0

    if not args.result_json or not args.result_json.is_file():
        raise SystemExit("Provide --result-json or --signature")

    result = json.loads(args.result_json.read_text(encoding="utf-8"))
    fee_est = (result.get("clmm") or {}).get("fee_guard_estimate") or result.get("fee_guard_estimate")
    rent = (fee_est or {}).get("rent_escrow") if isinstance(fee_est, dict) else None
    report = analyze_open_bundle(
        result,
        wallet=wallet,
        rpc_url=rpc,
        rent_escrow_estimate=rent,
        deposit_usd=args.deposit_usd,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
