"""Clean exit: close LP, burn ghosts, sweep to pay-type (USDC), update active_positions.json."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL_ID = "AoPimKYHxNTHAXXtqoespdaYVBVvEvjtYNvxGfmRdE2p"
SOL_PX = 180.0


def wallet_usd(bal: dict) -> float:
    return float(bal.get("sol_balance") or 0) * SOL_PX + float(bal.get("usdc_balance") or 0)


def main() -> int:
    from raydium_lp1.fee_guard import reset_session_ledger
    from raydium_lp1.lp_brainiac_cursor_success import (
        apply_brainiac_fee_and_settlement_settings,
        fee_settings_for_brainiac_procedure,
        settle_wallet_after_brainiac_trade,
    )
    from raydium_lp1.lp_junk_to_pay import sweep_junk_to_pay_leg
    from raydium_lp1.lp_order_rules import burn_all_empty_clmm_nfts, close_clmm_position
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.lp_tx_cost_analysis import analyze_transaction
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import _run_script, wallet_balance
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    load_dotenv()
    if get_mode() != "live":
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    scanner = ScannerConfig.from_file(REPO / "config" / "settings.json")
    fee = apply_brainiac_fee_and_settlement_settings(fee_settings_for_brainiac_procedure())
    pool = fetch_pool_by_id(POOL_ID, config=scanner)
    wallet = str(wallet_balance().get("address") or "")
    rpc = str(wallet_balance().get("rpc_url") or "")

    before = wallet_balance()
    w0 = wallet_usd(before)

    reset_session_ledger()
    report: dict = {
        "pool_id": POOL_ID,
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "started_at": datetime.now(UTC).isoformat(),
        "wallet_start_usd": round(w0, 4),
        "closes": [],
        "burns": [],
        "sweeps": [],
    }

    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    positions = chain.get("positions") or []
    pool_positions = [p for p in positions if str(p.get("pool_id")) == POOL_ID]

    for pos in pool_positions:
        nft = str(pos.get("position_nft_mint") or "")
        liq = int(pos.get("liquidity") or 0)
        if not nft:
            continue
        if liq > 0:
            print(f"\n=== CLOSE {nft[:12]}… liq={liq} ===", flush=True)
            cr = close_clmm_position(
                nft,
                pool=pool,
                config=scanner,
                fee_guard_settings=fee,
                slippage_bps=250,
                timeout=180.0,
            )
            report["closes"].append({"nft": nft, "liquidity": liq, "result": cr})
        else:
            print(f"\n=== BURN empty {nft[:12]}… ===", flush=True)
            from raydium_lp1.lp_order_rules import burn_empty_clmm_nft

            br = burn_empty_clmm_nft(nft, timeout=90.0)
            report["burns"].append({"nft": nft, "result": br})

    print("\n=== BURN all zero-liq ghosts (wallet) ===", flush=True)
    ghost_burns = burn_all_empty_clmm_nfts(positions=positions, timeout=90.0)
    report["burn_all_empty"] = ghost_burns

    print("\n=== SETTLE sweep to pay-type (USDC) ===", flush=True)
    settle = settle_wallet_after_brainiac_trade(pool, scanner, sol_price_usd=SOL_PX, fee_settings=fee)
    report["wallet_settlement"] = settle

    extra_sweep = sweep_junk_to_pay_leg(pool=pool, config=scanner)
    report["junk_sweep"] = extra_sweep

    after = wallet_balance()
    w1 = wallet_usd(after)
    report["wallet_end_usd"] = round(w1, 4)
    report["wallet_delta_usd"] = round(w1 - w0, 4)

    sigs: list[str] = []
    for row in report.get("closes") or []:
        r = row.get("result") or {}
        sigs.append(str(r.get("close_signature") or r.get("signature") or ""))
        for ts in r.get("trash_swaps") or []:
            if ts.get("signature"):
                sigs.append(str(ts["signature"]))
    fee_sol = 0.0
    for sig in sigs:
        if not sig:
            continue
        try:
            a = analyze_transaction(sig, wallet=wallet, rpc_url=rpc)
            fee_sol += float(a.fee_sol if hasattr(a, "fee_sol") else 0)
        except Exception:
            pass
    report["network_fees_usd"] = round(fee_sol * SOL_PX, 4)
    report["permanent_loss_usd"] = report["network_fees_usd"]
    report["capital_recovered_note"] = (
        f"Wallet (SOL+USDC) moved ${report['wallet_delta_usd']:+.2f}. "
        "ZINC value is not in that figure until swept or sold."
    )

    ap = REPO / "active_positions.json"
    if ap.exists():
        rows = json.loads(ap.read_text(encoding="utf-8"))
        kept = [r for r in rows if str(r.get("pool_id")) != POOL_ID]
        removed = len(rows) - len(kept)
        ap.write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
        report["active_positions_removed"] = removed

    report["ok"] = all(
        (c.get("result") or {}).get("ok") for c in report.get("closes") or []
    ) or not report.get("closes")
    report["finished_at"] = datetime.now(UTC).isoformat()

    out_path = REPO / "reports" / "clean_exit_zinc_usdc.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print("\n=== REPORT ===")
    print(json.dumps(report, indent=2, default=str))
    print(f"\nSaved: {out_path}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
