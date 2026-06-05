"""Close OOR ZINC/USDC bands, open one wide-band position (~$3.50, max 80% width)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL = "AoPimKYHxNTHAXXtqoespdaYVBVvEvjtYNvxGfmRdE2p"
CLOSE_NFTS = (
    "HuEon5sPAhmTTxBzNcfoTJbgykqjNaxY85T8DThiBjh6",
    "Ee3aidguyGdg7q2BmqtW9wNewvqUkvP2oXLMjArni6gf",
)
ACTIVE = REPO / "active_positions.json"
CLOSED = REPO / "closed_positions.json"


def _load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def _save(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    from raydium_lp1.fee_guard import reset_session_ledger
    from raydium_lp1.live_executor import open_clmm_candidate
    from raydium_lp1.lp_order_rules import close_clmm_position
    from raydium_lp1.lp_wallet_settlement import settle_wallet_after_trade
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import wallet_balance
    from raydium_lp1.scanner import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usd", type=float, default=3.5, help="Total LP budget (USD)")
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--sol-price", type=float, default=180.0)
    args = parser.parse_args()

    load_dotenv()
    if get_mode() != "live" and not args.preview_only:
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    plan = {"pool_id": POOL, "close_nfts": list(CLOSE_NFTS), "open_usd": args.usd}
    print(json.dumps({"plan": plan}, indent=2))
    if args.preview_only:
        return 0

    from raydium_lp1.raydium_clmm import _run_script

    ZINC_MINT = "zinc155BS4mSPk8GXQj4R5hkVDQXcW253pTYq5SGyfi"
    reset_session_ledger()
    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    on_pool = {
        str(p.get("position_nft_mint"))
        for p in (chain.get("positions") or [])
        if p.get("pool_id") == POOL
    }
    closed: list[dict] = []
    for nft in CLOSE_NFTS:
        if nft not in on_pool:
            print(f"skip close {nft[:16]}... (not on-chain)", flush=True)
            continue
        print(f"\n=== CLOSE {nft[:16]}... ===", flush=True)
        cr = close_clmm_position(nft, timeout=180.0)
        print(json.dumps(cr, indent=2, default=str))
        closed.append({"nft": nft, "close": cr})
        if not cr.get("ok"):
            return 1

    active = _load(ACTIVE)
    closed_rows = _load(CLOSED)
    now = datetime.now(UTC).isoformat()
    for nft in CLOSE_NFTS:
        row = next((r for r in active if str(r.get("position_nft_mint")) == nft), None)
        if row:
            arch = dict(row)
            arch["status"] = "closed_replace_zinc_full_range"
            arch["closed_at"] = now
            closed_rows.append(arch)
    active = [r for r in active if str(r.get("position_nft_mint")) not in set(CLOSE_NFTS)]
    _save(ACTIVE, active)
    _save(CLOSED, closed_rows[-250:])

    bal = wallet_balance()
    print(json.dumps({"balance_before_open": bal}, indent=2))

    settle = settle_wallet_after_trade(
        fund_usdc_target=None,
        sol_price_usd=float(args.sol_price),
        keep_mints=frozenset({ZINC_MINT}),
        sweep_junk=False,
    )
    print(json.dumps({"settle_pre_open": settle}, indent=2, default=str))

    print(f"\n=== OPEN wide band ZINC/USDC ${args.usd:.2f} (wallet inventory, max 80%) ===", flush=True)
    op = open_clmm_candidate(
        pool_id=POOL,
        input_amount_usd=float(args.usd),
        input_amount_sol=float(args.usd) / float(args.sol_price),
        wallet_inventory_full_range=True,
        strategy_id="standard_full_range",
        force_pay_token_only=False,
        sol_price_usd=float(args.sol_price),
    )
    print(json.dumps(op, indent=2, default=str))
    if not op.get("ok"):
        return 1

    settle_post = settle_wallet_after_trade(
        fund_usdc_target=None,
        sol_price_usd=float(args.sol_price),
        keep_mints=frozenset(),
        sweep_junk=True,
    )
    print(json.dumps({"settle_post_open": settle_post}, indent=2, default=str))

    nft = (op.get("clmm") or {}).get("position_nft_mint") or op.get("position_nft_mint")
    if nft:
        active = _load(ACTIVE)
        active.append(
            {
                "pool_id": POOL,
                "position_nft_mint": nft,
                "strategy_id": "standard_full_range",
                "status": "live_open",
                "opened_at": datetime.now(UTC).isoformat(),
                "notional_usd": float(args.usd),
            }
        )
        _save(ACTIVE, active)
        print(json.dumps({"recorded_nft": nft}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
