"""Close OOR SOL/IDLE positions on one pool; reopen N wide (80%) positions from proceeds."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL_ID = "CXuK5H4TZgb28vuucNoJh8LXRmR4VjdEuL6pXmMenSod"
SOL_MINT = "So11111111111111111111111111111111111111112"
IDLE_MINT = "AjLhrxN2yrCe45Y2KGPMZCkBm6NpN43jWqPkdZq6pump"


@dataclass
class WalletSnap:
    sol: float = 0.0
    idle_human: float = 0.0
    usdc_human: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"sol": round(self.sol, 6), "idle_human": self.idle_human, "usdc_human": self.usdc_human}


@dataclass
class CostLedger:
    pool_id: str = POOL_ID
    started_at: str = ""
    sol_price_usd: float = 180.0
    snaps: dict[str, WalletSnap] = field(default_factory=dict)
    closes: list[dict[str, Any]] = field(default_factory=list)
    opens: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def snap_wallet(self, label: str) -> WalletSnap:
        from raydium_lp1.raydium_clmm import wallet_balance, _run_script

        wb = wallet_balance()
        snap = WalletSnap(sol=float(wb.get("sol_balance") or wb.get("sol") or 0))
        snap.usdc_human = float(wb.get("usdc_balance") or 0)
        self.snaps[label] = snap
        return snap

    def usd(self, s: WalletSnap) -> float:
        return s.sol * self.sol_price_usd + s.idle_human / max(1.0, self._idle_per_sol()) + s.usdc_human

    def _idle_per_sol(self) -> float:
        from raydium_lp1.lp_selection import fetch_pool_by_id
        from raydium_lp1.scanner import ScannerConfig

        try:
            p = fetch_pool_by_id(self.pool_id, config=ScannerConfig.from_file(REPO / "config" / "settings.json"))
            return float(p.get("price") or 75210.0)
        except Exception:
            return 75210.0

    def finalize(self) -> dict[str, Any]:
        start = self.snaps.get("start") or WalletSnap()
        end = self.snaps.get("end") or WalletSnap()
        net_sol = end.sol - start.sol
        net_usd = self.usd(end) - self.usd(start)
        close_fee_sol = sum(float(c.get("network_fee_sol") or 0) for c in self.closes)
        open_fee_sol = sum(float(o.get("network_fee_sol") or 0) for o in self.opens)
        return {
            "pool_id": self.pool_id,
            "pair": "SOL/IDLE",
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "sol_price_usd": self.sol_price_usd,
            "wallet_start": start.to_dict(),
            "wallet_end": end.to_dict(),
            "wallet_net_sol": round(net_sol, 6),
            "wallet_net_usd_est": round(net_usd, 2),
            "close_count": len(self.closes),
            "open_count": len(self.opens),
            "close_network_fees_sol": round(close_fee_sol, 6),
            "open_network_fees_sol": round(open_fee_sol, 6),
            "total_network_fees_sol": round(close_fee_sol + open_fee_sol, 6),
            "total_network_fees_usd_est": round((close_fee_sol + open_fee_sol) * self.sol_price_usd, 4),
            "closes": self.closes,
            "opens": self.opens,
            "notes": self.notes,
        }


def _pool_tick_current_for(pool_id: str) -> int | None:
    import re
    import subprocess

    script = REPO / "src" / "raydium_lp1" / "raydium_clmm_node" / "probe_pool.mjs"
    try:
        proc = subprocess.run(
            ["node", str(script), pool_id, "0.001"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        text = (proc.stdout or "") + (proc.stderr or "")
        m = re.search(r"tickCurrent['\"]?\s*[:=]\s*(-?\d+)", text)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def _position_in_range(pos: dict[str, Any], tick_current: int | None) -> bool | None:
    if tick_current is None:
        return None
    lo = pos.get("tick_lower")
    hi = pos.get("tick_upper")
    if lo is None or hi is None:
        return None
    return int(lo) <= int(tick_current) <= int(hi)


def _tx_cost(sig: str, wallet: str, rpc: str) -> dict[str, Any]:
    from raydium_lp1.lp_tx_cost_analysis import analyze_transaction

    try:
        row = analyze_transaction(sig, wallet=wallet, rpc_url=rpc)
        return row.to_dict()
    except Exception as exc:
        return {"signature": sig, "error": str(exc)}


def main() -> int:
    from raydium_lp1.fee_guard import fee_config_from_settings, reset_session_ledger
    from raydium_lp1.live_executor import open_clmm_candidate
    from raydium_lp1.lp_order_rules import close_clmm_position
    from raydium_lp1.lp_order_strategies import STRATEGY_FULL_RANGE
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import _run_script, wallet_balance
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-id", default=POOL_ID)
    parser.add_argument("--new-positions", type=int, default=3)
    parser.add_argument("--reserve-sol", type=float, default=0.025, help="SOL kept for rent/fees")
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--sol-price", type=float, default=180.0)
    args = parser.parse_args()

    pool_id = str(args.pool_id).strip()

    load_dotenv()
    if get_mode() != "live" and not args.preview_only:
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    cfg = fee_config_from_settings()
    sol_px = float(args.sol_price or cfg.sol_price_usd or 180.0)
    ledger = CostLedger(
        pool_id=pool_id,
        started_at=datetime.now(UTC).isoformat(),
        sol_price_usd=sol_px,
    )

    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    if not chain.get("ok"):
        print(json.dumps(chain, indent=2))
        return 1

    tick_cur = _pool_tick_current_for(pool_id)
    pool_positions = [
        p for p in (chain.get("positions") or []) if str(p.get("pool_id") or "") == pool_id
    ]
    plan: list[dict[str, Any]] = []
    for pos in pool_positions:
        liq = int(pos.get("liquidity") or 0)
        ir = _position_in_range(pos, tick_cur)
        plan.append(
            {
                "nft": pos.get("position_nft_mint"),
                "tick_lower": pos.get("tick_lower"),
                "tick_upper": pos.get("tick_upper"),
                "liquidity": str(liq),
                "in_range": ir,
                "action": "keep" if ir else "close",
            }
        )

    preview = {
        "ok": True,
        "pool_id": pool_id,
        "tick_current": tick_cur,
        "positions": plan,
        "close_nfts": [p["nft"] for p in plan if p["action"] == "close" and int(p["liquidity"]) > 0],
        "keep_nfts": [p["nft"] for p in plan if p["action"] == "keep"],
        "new_opens": args.new_positions,
    }
    print(json.dumps(preview, indent=2))
    if args.preview_only:
        return 0

    reset_session_ledger()
    wb = wallet_balance()
    wallet = str(wb.get("address") or "")
    rpc = str(wb.get("rpc_url") or "")
    ledger.snap_wallet("start")

    for item in plan:
        if item["action"] != "close":
            continue
        if int(item["liquidity"]) <= 0:
            ledger.notes.append(f"skip zero-liq {item['nft']}")
            continue
        nft = str(item["nft"])
        print(f"\n=== CLOSE OOR {nft[:12]}... ===", flush=True)
        try:
            cr = close_clmm_position(nft, timeout=180.0)
        except Exception as exc:
            cr = {"ok": False, "error": str(exc)}
        sig = cr.get("close_signature") or cr.get("signature") or cr.get("tx") or ""
        cost = _tx_cost(sig, wallet, rpc) if sig else {}
        ledger.closes.append(
            {
                "nft": nft,
                "ok": bool(cr.get("ok")),
                "signature": sig,
                "network_fee_sol": cost.get("fee_sol"),
                "wallet_delta_sol": cost.get("wallet_delta_sol"),
                "error": cr.get("error"),
            }
        )
        print(json.dumps(cr, indent=2, default=str))

    from raydium_lp1.lp_wallet_settlement import settle_wallet_after_trade

    settle_wallet_after_trade(sol_price_usd=sol_px, sweep_junk=True)
    after_close = ledger.snap_wallet("after_closes")

    spendable_sol = max(0.0, after_close.sol - float(args.reserve_sol))
    budget_usd = spendable_sol * sol_px + after_close.idle_human / max(1.0, ledger._idle_per_sol()) * sol_px
    per_open_usd = budget_usd / max(1, args.new_positions) if budget_usd > 0 else 0.0
    ledger.notes.append(
        f"Reopen budget ~${budget_usd:.2f} total (~${per_open_usd:.2f} x {args.new_positions}) "
        f"after reserve {args.reserve_sol} SOL"
    )

    if per_open_usd < float(cfg.min_lp_deposit_usd or 0.25):
        ledger.snap_wallet("end")
        report = ledger.finalize()
        report["ok"] = False
        report["error"] = f"Budget per open ${per_open_usd:.2f} below min_lp_deposit_usd"
        out_path = REPO / "reports" / "sol_idle_rebalance_cost.json"
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    settings = json.loads((REPO / "config" / "settings.json").read_text(encoding="utf-8"))
    settings["lp_active_strategy"] = STRATEGY_FULL_RANGE

    for i in range(args.new_positions):
        print(f"\n=== OPEN {i + 1}/{args.new_positions} wide 80% ~${per_open_usd:.2f} ===", flush=True)
        try:
            result = open_clmm_candidate(
                pool_id=pool_id,
                input_amount_usd=per_open_usd,
                force_pay_token_only=True,
                strategy_id=STRATEGY_FULL_RANGE,
                wallet_inventory_full_range=True,
                sol_price_usd=sol_px,
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        sig = ""
        if result.get("ok"):
            sig = str(
                (result.get("clmm") or {}).get("signature")
                or result.get("tx")
                or (result.get("position") or {}).get("tx")
                or ""
            )
        cost = _tx_cost(sig, wallet, rpc) if sig else {}
        ledger.opens.append(
            {
                "index": i + 1,
                "deposit_usd": round(per_open_usd, 2),
                "ok": bool(result.get("ok")),
                "nft": (result.get("position") or {}).get("position_nft_mint")
                or (result.get("clmm") or {}).get("position_nft_mint"),
                "signature": sig,
                "network_fee_sol": cost.get("fee_sol"),
                "wallet_delta_sol": cost.get("wallet_delta_sol"),
                "wide_pay_only_fallback": (result.get("clmm") or {}).get("wide_pay_only_single_side_fallback"),
                "error": result.get("error"),
            }
        )
        print(json.dumps(result, indent=2, default=str)[:8000])

    settle_wallet_after_trade(sol_price_usd=sol_px, sweep_junk=True)
    ledger.snap_wallet("end")

    # Refresh active_positions.json from chain
    chain2 = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    active_rows: list[dict[str, Any]] = []
    for pos in chain2.get("positions") or []:
        if str(pos.get("pool_id") or "") != pool_id:
            continue
        if int(pos.get("liquidity") or 0) <= 0:
            continue
        active_rows.append(
            {
                "pool_id": pool_id,
                "pair": "SOL/IDLE",
                "position_nft_mint": pos.get("position_nft_mint"),
                "status": "live_open",
                "liquidity": pos.get("liquidity"),
                "tick_lower": pos.get("tick_lower"),
                "tick_upper": pos.get("tick_upper"),
                "lp_strategy_id": STRATEGY_FULL_RANGE,
                "rebalanced_at": datetime.now(UTC).isoformat(),
            }
        )
    (REPO / "active_positions.json").write_text(
        json.dumps(active_rows, indent=2) + "\n", encoding="utf-8"
    )

    report = ledger.finalize()
    report["ok"] = all(o.get("ok") for o in ledger.opens) if ledger.opens else False
    out_path = REPO / "reports" / "sol_idle_rebalance_cost.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("\n" + "=" * 60)
    print("COST SUMMARY")
    print("=" * 60)
    print(json.dumps(report, indent=2))
    print(f"\nReport: {out_path}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
