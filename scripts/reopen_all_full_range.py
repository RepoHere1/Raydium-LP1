"""Close every live CLMM position and reopen as standard_full_range (pay-token-only)."""

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
    if isinstance(raw, dict):
        return [dict(x) for x in (raw.get("positions") or raw.get("open") or []) if isinstance(x, dict)]
    return []


def _save_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def _deposit_sol(row: dict, *, floor_sol: float) -> float:
    for key in ("input_amount_sol", "input_amount_human"):
        try:
            v = float(row.get(key) or 0)
            if v > 0:
                return max(v, floor_sol)
        except (TypeError, ValueError):
            pass
    return floor_sol


def main() -> int:
    from raydium_lp1.live_executor import open_clmm_candidate
    from raydium_lp1.lp_order_rules import close_clmm_position
    from raydium_lp1.mode_toggle import get_mode
    from raydium_lp1.scanner import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usd-floor", type=float, default=0.15, help="Min reopen notional (USD)")
    parser.add_argument("--sol-price", type=float, default=float(__import__("os").environ.get("SOL_USD_PRICE", "180") or 180))
    parser.add_argument("--dry-run", action="store_true", help="List actions only")
    args = parser.parse_args()

    load_dotenv()
    if get_mode() != "live" and not args.dry_run:
        print(json.dumps({"ok": False, "error": "mode must be live"}, indent=2))
        return 1

    floor_sol = max(0.000833, float(args.usd_floor) / float(args.sol_price))
    from raydium_lp1.raydium_clmm import _run_script

    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    on_chain = chain.get("positions") if chain.get("ok") else []
    json_live = [r for r in _load_rows(ACTIVE) if r.get("status") == "live_open" and r.get("pool_id")]

    close_plan = [
        {"nft": p["position_nft_mint"], "pool_id": p["pool_id"], "liquidity": p.get("liquidity")}
        for p in on_chain
    ]
    reopen_by_pool: dict[str, dict] = {}
    for row in json_live:
        pid = str(row.get("pool_id") or "")
        if not pid:
            continue
        dep = _deposit_sol(row, floor_sol=floor_sol)
        prev = reopen_by_pool.get(pid)
        if prev is None or dep > float(prev.get("deposit_sol") or 0):
            reopen_by_pool[pid] = {
                "pair": row.get("pair"),
                "pool_id": pid,
                "deposit_sol": dep,
            }
    # Also reopen pools we had multiple positions on (count from json)
    pool_counts: dict[str, int] = {}
    for row in json_live:
        pid = str(row.get("pool_id") or "")
        pool_counts[pid] = pool_counts.get(pid, 0) + 1
    reopen_plan = []
    for pid, meta in reopen_by_pool.items():
        n = pool_counts.get(pid, 1)
        for _ in range(n):
            reopen_plan.append(dict(meta))

    if not close_plan and not reopen_plan:
        print(json.dumps({"ok": False, "error": "nothing on-chain and no pools in active_positions.json"}, indent=2))
        return 1

    plan = close_plan  # legacy name for close loop

    print(json.dumps({
        "action": "plan",
        "close_on_chain": close_plan,
        "reopen": reopen_plan,
        "strategy": STRATEGY,
    }, indent=2))
    if args.dry_run:
        return 0

    closed_log: list[dict] = []
    reopened: list[dict] = []
    errors: list[dict] = []

    for item in close_plan:
        nft = str(item["nft"])
        print(f"\n=== CLOSE on-chain {nft[:16]}... pool={str(item.get('pool_id',''))[:12]} ===", flush=True)
        try:
            cr = close_clmm_position(nft, timeout=180.0)
        except Exception as exc:
            cr = {"ok": False, "error": str(exc)}
        print(json.dumps(cr, indent=2, default=str))
        closed_log.append({**item, "close": cr})
        if not cr.get("ok"):
            errors.append({"phase": "close", **item, "error": cr.get("error")})
            continue

    remaining = [r for r in _load_rows(ACTIVE) if r.get("status") == "live_open"]
    closed_rows = _load_rows(CLOSED)
    for row in remaining:
        nft = str(row.get("position_nft_mint") or "")
        hit = next((c for c in closed_log if c["nft"] == nft and (c.get("close") or {}).get("ok")), None)
        if hit:
            row = dict(row)
            row["status"] = "closed_reopen_full_range"
            row["closed_at"] = _now_iso()
            row["close_result"] = hit["close"]
            closed_rows.append(row)
    closed_nfts = {c["nft"] for c in closed_log if (c.get("close") or {}).get("ok")}
    still_live = [r for r in remaining if str(r.get("position_nft_mint")) not in closed_nfts]
    _save_rows(CLOSED, closed_rows[-200:])

    for item in reopen_plan:
        pool_id = str(item["pool_id"])
        dep = float(item["deposit_sol"])
        print(f"\n=== OPEN LIVE {item.get('pair')} pool={pool_id[:12]}... ~${dep * args.sol_price:.2f} ===", flush=True)
        usd_open = float(args.usd_floor) if "USDC" in str(item.get("pair") or "").upper() else None
        try:
            op = open_clmm_candidate(
                pool_id=pool_id,
                input_amount_sol=dep,
                input_amount_usd=usd_open,
                force_pay_token_only=True,
                strategy_id=STRATEGY,
                sol_price_usd=float(args.sol_price),
            )
        except Exception as exc:
            op = {"ok": False, "error": str(exc)}
        print(json.dumps(op, indent=2, default=str))
        if op.get("ok"):
            reopened.append(op.get("position") or op)
        else:
            errors.append({"phase": "open", **item, "error": op.get("error")})

    new_active = still_live + [r for r in reopened if isinstance(r, dict)]
    _save_rows(ACTIVE, new_active)

    summary = {
        "ok": len(errors) == 0 and len(reopened) == len(reopen_plan),
        "closed_ok": sum(1 for c in closed_log if (c.get("close") or {}).get("ok")),
        "reopen_target": len(reopen_plan),
        "reopened_ok": len(reopened),
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
