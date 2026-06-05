"""Close + reopen LIVE wide-band strategy positions that use wrong ticks (narrow or literal min/max)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

ACTIVE = REPO / "active_positions.json"
CLOSED = REPO / "closed_positions.json"
STRATEGY = "standard_full_range"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [dict(x) for x in raw if isinstance(x, dict)]
    return []


def _save_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def _deposit_amounts(row: dict, *, sol_price: float) -> tuple[float | None, float]:
    """Return (input_amount_usd, input_amount_sol) for reopen."""

    sym = str(row.get("lp_pay_symbol") or row.get("input_pay_symbol") or "").upper()
    human = row.get("input_amount_human") or row.get("input_amount_sol")
    try:
        amt = float(human or 0)
    except (TypeError, ValueError):
        amt = 0.15
    if sym in ("USDC", "USDT", "USD1"):
        usd = max(0.15, amt)
        return usd, usd / max(sol_price, 1.0)
    sol = max(0.000833, amt)
    return None, sol


def _needs_full_range_repair(row: dict) -> bool:
    from raydium_lp1.lp_full_range import is_wide_band_position, position_spans_full_ticks

    if not is_wide_band_position(row):
        return False
    clmm = row.get("clmm_result") if isinstance(row.get("clmm_result"), dict) else {}
    if position_spans_full_ticks(clmm):
        return True
    if clmm.get("wide_range") and not position_spans_full_ticks(clmm):
        return False
    return not position_spans_full_ticks(clmm)


def _audit_other_strategies(live_rows: list[dict]) -> list[dict]:
    """Flag likely metadata/tick mismatches (informational)."""
    notes: list[dict] = []
    for row in live_rows:
        if row.get("status") != "live_open":
            continue
        sid = str(row.get("lp_strategy_id") or "")
        placement = str(row.get("lp_placement") or "")
        clmm = row.get("clmm_result") if isinstance(row.get("clmm_result"), dict) else {}
        mode = str(clmm.get("single_side_mode") or "").lower()
        params = row.get("lp_open_params") if isinstance(row.get("lp_open_params"), dict) else {}

        if sid in ("centered_tight_range", "auto_volatility_pick") and placement == "centered":
            if mode in ("above", "below"):
                notes.append(
                    {
                        "nft": row.get("position_nft_mint"),
                        "issue": "centered_strategy_but_single_side_on_chain",
                        "strategy": sid,
                        "pair": row.get("pair"),
                    }
                )
        if sid == "trailing_dynamic_skew" and placement == "single_above" and mode != "above":
            notes.append(
                {
                    "nft": row.get("position_nft_mint"),
                    "issue": "trailing_skew_placement_vs_chain_mode",
                    "chain_mode": mode,
                    "pair": row.get("pair"),
                }
            )
        if params.get("tick_lower_pct_below") and params.get("single_side") in ("above", "below"):
            notes.append(
                {
                    "nft": row.get("position_nft_mint"),
                    "issue": "stale_open_params_both_pct_and_single_side",
                    "strategy": sid,
                }
            )
    return notes


def main() -> int:
    from raydium_lp1.live_executor import open_clmm_candidate
    from raydium_lp1.lp_order_rules import close_clmm_position
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.raydium_clmm import _run_script
    from raydium_lp1.scanner import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sol-price", type=float, default=180.0)
    args = parser.parse_args()

    load_dotenv()
    if get_mode() != "live" and not args.dry_run:
        print(json.dumps({"ok": False, "error": "mode must be LIVE"}, indent=2))
        return 1

    live_json = [r for r in _load_rows(ACTIVE) if r.get("status") == "live_open"]
    repair_rows = [r for r in live_json if _needs_full_range_repair(r)]
    audit = _audit_other_strategies(live_json)

    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    on_chain = {str(p.get("position_nft_mint")): p for p in (chain.get("positions") or []) if chain.get("ok")}

    plan = []
    ghosts = []
    for row in repair_rows:
        nft = str(row.get("position_nft_mint") or "")
        oc = on_chain.get(nft)
        usd_amt, sol_amt = _deposit_amounts(row, sol_price=args.sol_price)
        entry = {
            "nft": nft,
            "pool_id": row.get("pool_id"),
            "pair": row.get("pair"),
            "input_amount_usd": usd_amt,
            "input_amount_sol": sol_amt,
            "on_chain": bool(oc),
            "on_chain_liquidity": (oc or {}).get("liquidity"),
            "tick_lower": (row.get("clmm_result") or {}).get("tick_lower"),
            "tick_upper": (row.get("clmm_result") or {}).get("tick_upper"),
            "tick_spacing": (row.get("clmm_result") or {}).get("tick_spacing"),
        }
        if oc:
            plan.append(entry)
        else:
            ghosts.append(entry)

    print(
        json.dumps(
            {
                "action": "repair_full_range_plan",
                "repair_count": len(plan),
                "repair_on_chain": plan,
                "ghost_json_only": ghosts,
                "other_strategy_audit": audit,
            },
            indent=2,
        )
    )
    if args.dry_run:
        return 0

    if ghosts:
        closed_rows = _load_rows(CLOSED)
        for g in ghosts:
            nft = str(g["nft"])
            row = next((r for r in live_json if str(r.get("position_nft_mint")) == nft), None)
            if row:
                archived = dict(row)
                archived["status"] = "closed_repair_full_range_ghost"
                archived["closed_at"] = _now_iso()
                archived["note"] = "not on chain; pruned from active"
                closed_rows.append(archived)
        _save_rows(CLOSED, closed_rows[-250:])
        live_json = [
            r
            for r in live_json
            if str(r.get("position_nft_mint")) not in {g["nft"] for g in ghosts}
        ]
        _save_rows(ACTIVE, live_json)

    if not plan:
        print(json.dumps({"ok": True, "repaired_on_chain": 0, "ghosts_pruned": len(ghosts)}, indent=2))
        return 0

    errors: list[dict] = []
    reopened: list[dict] = []
    closed_rows = _load_rows(CLOSED)
    remaining = [r for r in _load_rows(ACTIVE) if r.get("status") == "live_open"]

    for item in plan:
        nft = str(item["nft"])
        print(f"\n=== CLOSE (repair full range) {nft[:16]}... ===", flush=True)
        try:
            cr = close_clmm_position(nft, timeout=180.0)
        except Exception as exc:
            cr = {"ok": False, "error": str(exc)}
        print(json.dumps(cr, indent=2, default=str))
        if not cr.get("ok"):
            errors.append({"phase": "close", **item, "error": cr.get("error")})
            continue

        row = next((r for r in remaining if str(r.get("position_nft_mint")) == nft), None)
        if row:
            archived = dict(row)
            archived["status"] = "closed_repair_full_range"
            archived["closed_at"] = _now_iso()
            archived["close_result"] = cr
            closed_rows.append(archived)
            remaining = [r for r in remaining if str(r.get("position_nft_mint")) != nft]

        pool_id = str(item["pool_id"])
        sym = str(item.get("pair") or "")
        use_usd = item.get("input_amount_usd")
        dep_sol = float(item["input_amount_sol"])

        from raydium_lp1.raydium_clmm import wallet_balance

        bal = wallet_balance()
        usdc_now = float(bal.get("usdc_balance") or 0)
        sol_now = float(bal.get("sol_balance") or 0)
        if use_usd is not None and usdc_now > 0:
            use_usd = min(float(use_usd), max(0.15, usdc_now * 0.92))
            dep_sol = float(use_usd) / max(float(args.sol_price), 1.0)

        label = f"${use_usd:.2f}" if use_usd is not None else f"{dep_sol:.6f} SOL"
        print(f"\n=== REOPEN wide band (max 80%) {sym} pool={pool_id[:12]}... {label} ===", flush=True)
        try:
            op = open_clmm_candidate(
                pool_id=pool_id,
                input_amount_sol=dep_sol,
                input_amount_usd=float(use_usd) if use_usd is not None else None,
                wallet_inventory_full_range=True,
                force_pay_token_only=False,
                strategy_id=STRATEGY,
                sol_price_usd=args.sol_price,
            )
        except Exception as exc:
            op = {"ok": False, "error": str(exc)}
        print(json.dumps(op, indent=2, default=str))
        if op.get("ok"):
            pos = op.get("position") if isinstance(op.get("position"), dict) else op
            reopened.append(pos)
            clmm = pos.get("clmm_result") if isinstance(pos, dict) else {}
            if clmm.get("tick_lower") is not None:
                from raydium_lp1.lp_full_range import position_spans_full_ticks

                print(
                    "  wide_range:",
                    clmm.get("wide_range"),
                    "literal_ticks:",
                    position_spans_full_ticks(clmm),
                    "lo",
                    clmm.get("tick_lower"),
                    "hi",
                    clmm.get("tick_upper"),
                )
        else:
            errors.append({"phase": "open", **item, "error": op.get("error")})

    new_active = remaining + [r for r in reopened if isinstance(r, dict)]
    _save_rows(ACTIVE, new_active)
    _save_rows(CLOSED, closed_rows[-250:])

    summary = {
        "ok": len(errors) == 0 and len(reopened) == len(plan),
        "repair_target": len(plan),
        "reopened_ok": len(reopened),
        "errors": errors,
        "other_strategy_audit": audit,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
