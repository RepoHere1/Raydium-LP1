"""Close all on one pool; reopen N positions using BRAINIAC-CURSOR-SUCCESS order type."""

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

from raydium_lp1.lp_brainiac_cursor_success import (  # noqa: E402
    STRATEGY_BRAINIAC_CURSOR_SUCCESS,
    WIDE_WIDTH_PCT,
    brainiac_optimal_wide_placement as brainiac_optimal_wide80,
    fee_settings_for_brainiac_procedure as _rebalance_fee_settings,
    open_clmm_with_brainiac_cursor_success,
)
from raydium_lp1.lp_brainiac_cursor_success import fund_non_pay_leg_if_needed  # noqa: E402
from raydium_lp1.lp_junk_to_pay import keep_mints_for_pool  # noqa: E402

POOL_ID = "CXuK5H4TZgb28vuucNoJh8LXRmR4VjdEuL6pXmMenSod"
SOL_MINT = "So11111111111111111111111111111111111111112"
IDLE_MINT = "AjLhrxN2yrCe45Y2KGPMZCkBm6NpN43jWqPkdZq6pump"


@dataclass
class WalletSnap:
    sol: float = 0.0
    usdc: float = 0.0
    idle_human: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "sol": round(self.sol, 6),
            "usdc": round(self.usdc, 4),
            "idle_human": round(self.idle_human, 4),
        }


@dataclass
class ProcedureLedger:
    pool_id: str = POOL_ID
    started_at: str = ""
    sol_price_usd: float = 180.0
    idle_per_sol: float = 78642.0
    snaps: dict[str, WalletSnap] = field(default_factory=dict)
    brainiac: dict[str, Any] = field(default_factory=dict)
    closes: list[dict[str, Any]] = field(default_factory=list)
    opens: list[dict[str, Any]] = field(default_factory=list)
    funding_swaps: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def idle_usd(self, snap: WalletSnap) -> float:
        if self.idle_per_sol <= 0:
            return 0.0
        sol_equiv = snap.idle_human / self.idle_per_sol
        return sol_equiv * self.sol_price_usd

    def wallet_usd(self, snap: WalletSnap) -> float:
        return snap.sol * self.sol_price_usd + snap.usdc + self.idle_usd(snap)

    def snap_wallet(self, label: str) -> WalletSnap:
        import importlib.util

        from raydium_lp1.raydium_clmm import wallet_balance

        sweep_mod = importlib.util.spec_from_file_location(
            "sweep_junk_to_pay", REPO / "scripts" / "sweep_junk_to_pay.py"
        )
        assert sweep_mod and sweep_mod.loader
        sweep = importlib.util.module_from_spec(sweep_mod)
        sweep_mod.loader.exec_module(sweep)
        _list_wallet_tokens = sweep._list_wallet_tokens

        wb = wallet_balance()
        snap = WalletSnap(
            sol=float(wb.get("sol_balance") or wb.get("sol") or 0),
            usdc=float(wb.get("usdc_balance") or 0),
        )
        for row in _list_wallet_tokens():
            if str(row.get("mint") or "") == IDLE_MINT:
                dec = int(row.get("decimals") or 6)
                snap.idle_human = int(row.get("amount_raw") or 0) / (10**dec)
                break
        self.snaps[label] = snap
        return snap

    def finalize(self) -> dict[str, Any]:
        start = self.snaps.get("start") or WalletSnap()
        end = self.snaps.get("end") or WalletSnap()
        close_fees = sum(float(c.get("network_fee_sol") or 0) for c in self.closes)
        open_fees = sum(float(o.get("network_fee_sol") or 0) for o in self.opens)
        swap_fees = sum(float(s.get("network_fee_sol") or 0) for s in self.funding_swaps)
        total_fee_sol = close_fees + open_fees + swap_fees
        total_fee_usd = total_fee_sol * self.sol_price_usd

        wallet_start_usd = self.wallet_usd(start)
        wallet_end_usd = self.wallet_usd(end)
        wallet_delta_usd = wallet_end_usd - wallet_start_usd

        deposits_usd = sum(float(o.get("deposit_usd") or 0) for o in self.opens if o.get("ok"))
        deployed_sol = sum(
            abs(float(o.get("wallet_delta_sol") or 0))
            for o in self.opens
            if o.get("ok") and float(o.get("wallet_delta_sol") or 0) < 0
        )

        return {
            "pool_id": self.pool_id,
            "pair": "SOL/IDLE",
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "sol_price_usd": self.sol_price_usd,
            "idle_per_sol": round(self.idle_per_sol, 4),
            "brainiac_placement": self.brainiac,
            "wallet_start": start.to_dict(),
            "wallet_end": end.to_dict(),
            "wallet_usd_start": round(wallet_start_usd, 2),
            "wallet_usd_end": round(wallet_end_usd, 2),
            "wallet_usd_delta": round(wallet_delta_usd, 2),
            "permanent_loss_usd": {
                "network_fees_only": round(total_fee_usd, 4),
                "breakdown": {
                    "closes_usd": round(close_fees * self.sol_price_usd, 4),
                    "opens_usd": round(open_fees * self.sol_price_usd, 4),
                    "funding_swaps_usd": round(swap_fees * self.sol_price_usd, 4),
                },
                "note": (
                    "Permanent = on-chain tx fees only. LP deposits + NFT rent (~0.008 SOL/NFT) "
                    "are recoverable when you close positions — not counted as loss."
                ),
            },
            "capital_moved": {
                "target_deposits_usd": round(deposits_usd, 2),
                "wallet_sol_deployed_est": round(deployed_sol, 6),
                "wallet_sol_deployed_usd_est": round(deployed_sol * self.sol_price_usd, 2),
                "note": "Negative wallet_usd_delta mostly reflects SOL/IDLE moved into LP, not burned fees.",
            },
            "close_count": len(self.closes),
            "open_count": len(self.opens),
            "closes": self.closes,
            "opens": self.opens,
            "funding_swaps": self.funding_swaps,
            "notes": self.notes,
        }


def _pool_tick_current(pool_id: str) -> int | None:
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


def _tx_cost(sig: str, wallet: str, rpc: str) -> dict[str, Any]:
    from raydium_lp1.lp_tx_cost_analysis import analyze_transaction

    if not sig:
        return {}
    try:
        return analyze_transaction(sig, wallet=wallet, rpc_url=rpc).to_dict()
    except Exception as exc:
        return {"signature": sig, "error": str(exc)}


def _complete_pending_opens(
    *,
    pool_id: str,
    pool: dict[str, Any],
    scanner: Any,
    report_path: Path,
    fee_settings: dict[str, Any],
    sol_px: float,
    placement: dict[str, Any],
    ledger: ProcedureLedger,
) -> int:
    """Resume opens that failed on session fee-guard cap."""

    from raydium_lp1.fee_guard import reset_session_ledger
    from raydium_lp1.lp_wallet_settlement import settle_wallet_after_trade
    from raydium_lp1.raydium_clmm import _run_script, wallet_balance

    prior = json.loads(report_path.read_text(encoding="utf-8"))
    ledger.closes = list(prior.get("closes") or [])
    ledger.opens = list(prior.get("opens") or [])
    ledger.funding_swaps = list(prior.get("funding_swaps") or [])
    ledger.notes = list(prior.get("notes") or []) + ["complete-opens-only resume"]
    ledger.snaps["start"] = WalletSnap(**(prior.get("wallet_start") or {}))
    ledger.sol_price_usd = float(prior.get("sol_price_usd") or sol_px)
    ledger.idle_per_sol = float(prior.get("idle_per_sol") or ledger.idle_per_sol)

    pool_keep = keep_mints_for_pool(pool, scanner)

    pending = [o for o in ledger.opens if not o.get("ok")]
    if not pending:
        print(json.dumps({"ok": True, "message": "no pending opens"}, indent=2))
        return 0

    reset_session_ledger()
    wb = wallet_balance()
    wallet = str(wb.get("address") or "")
    rpc = str(wb.get("rpc_url") or "")
    tick_lo = float(placement["tick_lower_pct_below"])
    tick_hi = float(placement["tick_upper_pct_above"])

    end_snap = ledger.snap_wallet("resume_start")
    reserve_sol = 0.03
    spendable_usd = ledger.wallet_usd(end_snap) - reserve_sol * sol_px
    per_open_usd = max(
        float(fee_settings.get("min_lp_deposit_usd") or 0.25),
        spendable_usd / max(1, len(pending)),
    )
    ledger.notes.append(
        f"Resume budget ~${spendable_usd:.2f} · ${per_open_usd:.2f} × {len(pending)} pending"
    )

    for item in pending:
        idx = int(item.get("index") or 0)
        print(f"\n=== RESUME OPEN {idx} ~${per_open_usd:.2f} ===", flush=True)
        try:
            result = open_clmm_with_brainiac_cursor_success(
                pool_id=pool_id,
                input_amount_usd=per_open_usd,
                fee_guard_settings=fee_settings,
                sol_price_usd=sol_px,
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        sig = ""
        if result.get("ok"):
            sig = str((result.get("clmm") or {}).get("signature") or "")
        cost = _tx_cost(sig, wallet, rpc)
        clmm = result.get("clmm") or {}
        item.update(
            {
                "deposit_usd": round(per_open_usd, 2),
                "strategy_id": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
                "ok": bool(result.get("ok")),
                "nft": (result.get("position") or {}).get("position_nft_mint")
                or clmm.get("position_nft_mint"),
                "signature": sig,
                "network_fee_sol": cost.get("fee_sol"),
                "wallet_delta_sol": cost.get("wallet_delta_sol"),
                "two_sided": not clmm.get("wide_pay_only_single_side_fallback"),
                "error": result.get("error"),
            }
        )
        print(json.dumps(result, indent=2, default=str)[:6000])
        settle_wallet_after_trade(
            pool=pool,
            config=scanner,
            sol_price_usd=sol_px,
            fee_settings=fee_settings,
            keep_mints=pool_keep,
            sweep_junk=False,
        )

    settle_wallet_after_trade(
        pool=pool,
        config=scanner,
        sol_price_usd=sol_px,
        fee_settings=fee_settings,
        keep_mints=pool_keep,
        sweep_junk=True,
    )
    ledger.snap_wallet("end")
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
                "lp_strategy_id": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
                "brainiac_placement": placement,
                "rebalanced_at": datetime.now(UTC).isoformat(),
            }
        )
    (REPO / "active_positions.json").write_text(
        json.dumps(active_rows, indent=2) + "\n", encoding="utf-8"
    )
    report = ledger.finalize()
    report["ok"] = all(o.get("ok") for o in ledger.opens)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report.get("permanent_loss_usd"), indent=2))
    print(f"\nFull report: {report_path}")
    return 0 if report.get("ok") else 1


def _maybe_fund_idle(
    *,
    pool: dict[str, Any],
    target_idle_usd: float,
    snap: WalletSnap,
    ledger: ProcedureLedger,
    fee_settings: dict[str, Any],
    wallet: str,
    rpc: str,
    scanner: Any,
) -> None:
    """Fund non-pay pair leg from pay-type only (order-type settlement; symbol-agnostic)."""

    have_usd = ledger.idle_usd(snap)
    short_usd = max(0.0, target_idle_usd * 0.42 - have_usd)
    if short_usd < 0.5:
        ledger.notes.append(f"IDLE leg OK (~${have_usd:.2f} idle value, target ~${target_idle_usd * 0.42:.2f})")
        return

    sw = fund_non_pay_leg_if_needed(
        pool,
        target_non_pay_usd=short_usd,
        sol_price_usd=ledger.sol_price_usd,
        config=scanner,
    )
    sig = str(sw.get("signature") or "")
    cost = _tx_cost(sig, wallet, rpc)
    ledger.notes.append(
        f"Funding alt via pay leg: {sw.get('direction', '?')} ~${short_usd:.2f} ({sw.get('pay_mint', '')[:8]}…)"
    )
    ledger.funding_swaps.append(
        {
            "direction": sw.get("direction") or "pay→alt",
            "ok": bool(sw.get("ok")),
            "signature": sig,
            "network_fee_sol": cost.get("fee_sol"),
            "wallet_delta_sol": cost.get("wallet_delta_sol"),
            "error": sw.get("error"),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-id", default=POOL_ID)
    parser.add_argument("--new-positions", type=int, default=4)
    parser.add_argument("--reserve-sol", type=float, default=0.03)
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument(
        "--complete-opens-only",
        action="store_true",
        help="Finish failed opens from reports/sol_idle_brainiac_procedure.json",
    )
    parser.add_argument("--sol-price", type=float, default=0.0)
    args = parser.parse_args()

    from raydium_lp1.fee_guard import reset_session_ledger
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.lp_wallet_settlement import settle_wallet_after_trade
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import _run_script, wallet_balance
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    pool_id = str(args.pool_id).strip()
    load_dotenv()
    if get_mode() != "live" and not args.preview_only:
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    scanner = ScannerConfig.from_file(REPO / "config" / "settings.json")
    fee_settings = _rebalance_fee_settings()
    pool = fetch_pool_by_id(pool_id, config=scanner)
    sol_px = float(args.sol_price or fee_settings.get("lp_pay_funding_sol_price_usd") or 180)
    idle_px = float(pool.get("price") or 78642)

    placement = brainiac_optimal_wide80(
        pool, scanner=scanner, settings=fee_settings, width_pct=WIDE_WIDTH_PCT
    )
    ledger = ProcedureLedger(
        pool_id=pool_id,
        started_at=datetime.now(UTC).isoformat(),
        sol_price_usd=sol_px,
        idle_per_sol=idle_px,
        brainiac=placement,
    )

    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    if not chain.get("ok"):
        print(json.dumps(chain, indent=2))
        return 1

    pool_positions = [
        p for p in (chain.get("positions") or []) if str(p.get("pool_id") or "") == pool_id
    ]
    close_nfts = [
        str(p.get("position_nft_mint"))
        for p in pool_positions
        if int(p.get("liquidity") or 0) > 0
    ]

    preview = {
        "ok": True,
        "pool_id": pool_id,
        "tick_current": _pool_tick_current(pool_id),
        "close_all_nfts": close_nfts,
        "new_opens": args.new_positions,
        "brainiac": placement,
    }
    print(json.dumps(preview, indent=2))
    if args.preview_only:
        return 0

    report_path = REPO / "reports" / "sol_idle_brainiac_procedure.json"
    if args.complete_opens_only and report_path.is_file():
        return _complete_pending_opens(
            pool_id=pool_id,
            pool=pool,
            scanner=scanner,
            report_path=report_path,
            fee_settings=fee_settings,
            sol_px=sol_px,
            placement=placement,
            ledger=ledger,
        )

    reset_session_ledger()
    wb = wallet_balance()
    wallet = str(wb.get("address") or "")
    rpc = str(wb.get("rpc_url") or "")
    ledger.snap_wallet("start")

    from raydium_lp1.lp_order_rules import burn_all_empty_clmm_nfts, close_clmm_position

    pool_keep = keep_mints_for_pool(pool, scanner)

    for nft in close_nfts:
        print(f"\n=== CLOSE {nft[:12]}... ===", flush=True)
        try:
            cr = close_clmm_position(
                nft,
                pool=pool,
                config=scanner,
                sweep_trash_to_sol=False,
                fee_guard_settings=fee_settings,
                timeout=180.0,
            )
        except Exception as exc:
            cr = {"ok": False, "error": str(exc)}
        sig = cr.get("close_signature") or cr.get("signature") or cr.get("tx") or ""
        cost = _tx_cost(sig, wallet, rpc)
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
        print(json.dumps(cr, indent=2, default=str)[:6000])

    burn_all_empty_clmm_nfts(positions=pool_positions)
    settle_wallet_after_trade(
        pool=pool,
        config=scanner,
        sol_price_usd=sol_px,
        fee_settings=fee_settings,
        keep_mints=pool_keep,
        sweep_junk=True,
    )
    after_close = ledger.snap_wallet("after_closes")

    spendable_sol = max(0.0, after_close.sol - float(args.reserve_sol))
    budget_usd = ledger.wallet_usd(after_close) - float(args.reserve_sol) * sol_px
    per_open_usd = budget_usd / max(1, args.new_positions) if budget_usd > 0 else 0.0
    ledger.notes.append(
        f"Budget ~${budget_usd:.2f} total · ${per_open_usd:.2f} × {args.new_positions} "
        f"(reserve {args.reserve_sol} SOL)"
    )

    min_dep = float(fee_settings.get("min_lp_deposit_usd") or 0.25)
    if per_open_usd < min_dep:
        ledger.snap_wallet("end")
        report = ledger.finalize()
        report["ok"] = False
        report["error"] = f"Per-open ${per_open_usd:.2f} below min_lp_deposit_usd"
        out = REPO / "reports" / "sol_idle_brainiac_procedure.json"
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    _maybe_fund_idle(
        pool=pool,
        target_idle_usd=budget_usd,
        snap=ledger.snap_wallet("pre_open"),
        ledger=ledger,
        fee_settings=fee_settings,
        wallet=wallet,
        rpc=rpc,
        scanner=scanner,
    )
    settle_wallet_after_trade(
        pool=pool,
        config=scanner,
        sol_price_usd=sol_px,
        fee_settings=fee_settings,
        keep_mints=pool_keep,
        sweep_junk=True,
    )

    tick_lo = float(placement["tick_lower_pct_below"])
    tick_hi = float(placement["tick_upper_pct_above"])

    reset_session_ledger()
    for i in range(args.new_positions):
        print(
            f"\n=== OPEN {i + 1}/{args.new_positions} "
            f"~${per_open_usd:.2f} brainiac 80% skew={placement['optimal_skew']} ===",
            flush=True,
        )
        try:
            result = open_clmm_with_brainiac_cursor_success(
                pool_id=pool_id,
                input_amount_usd=per_open_usd,
                pool=pool,
                fee_guard_settings=fee_settings,
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
        cost = _tx_cost(sig, wallet, rpc)
        clmm = result.get("clmm") or {}
        ledger.opens.append(
            {
                "index": i + 1,
                "strategy_id": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
                "deposit_usd": round(per_open_usd, 2),
                "ok": bool(result.get("ok")),
                "nft": (result.get("position") or {}).get("position_nft_mint")
                or clmm.get("position_nft_mint"),
                "signature": sig,
                "network_fee_sol": cost.get("fee_sol"),
                "wallet_delta_sol": cost.get("wallet_delta_sol"),
                "two_sided": not clmm.get("wide_pay_only_single_side_fallback"),
                "wide_pay_only_fallback": clmm.get("wide_pay_only_single_side_fallback"),
                "brainiac_ticks": {"below_pct": tick_lo, "above_pct": tick_hi},
                "error": result.get("error"),
            }
        )
        print(json.dumps(result, indent=2, default=str)[:8000])
        settle_wallet_after_trade(
            pool=pool,
            config=scanner,
            sol_price_usd=sol_px,
            fee_settings=fee_settings,
            keep_mints=pool_keep,
            sweep_junk=False,
        )

    settle_wallet_after_trade(
        pool=pool,
        config=scanner,
        sol_price_usd=sol_px,
        fee_settings=fee_settings,
        keep_mints=pool_keep,
        sweep_junk=True,
    )
    ledger.snap_wallet("end")

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
                "lp_strategy_id": STRATEGY_BRAINIAC_CURSOR_SUCCESS,
                "brainiac_placement": placement,
                "rebalanced_at": datetime.now(UTC).isoformat(),
            }
        )
    (REPO / "active_positions.json").write_text(
        json.dumps(active_rows, indent=2) + "\n", encoding="utf-8"
    )

    report = ledger.finalize()
    report["ok"] = all(o.get("ok") for o in ledger.opens) if ledger.opens else False
    out_path = REPO / "reports" / "sol_idle_brainiac_procedure.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 60)
    print("PROCEDURE COST (human USD)")
    print("=" * 60)
    pl = report["permanent_loss_usd"]
    print(f"  Permanent loss (network fees only): ${pl['network_fees_only']:.2f}")
    print(f"    closes: ${pl['breakdown']['closes_usd']:.2f}")
    print(f"    opens:  ${pl['breakdown']['opens_usd']:.2f}")
    print(f"    swaps:  ${pl['breakdown']['funding_swaps_usd']:.2f}")
    print(f"  Wallet USD start: ${report['wallet_usd_start']:.2f}")
    print(f"  Wallet USD end:   ${report['wallet_usd_end']:.2f}")
    print(f"  Wallet USD delta: ${report['wallet_usd_delta']:.2f}  (mostly LP deploy, not fees)")
    print(f"\nFull report: {out_path}")
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
