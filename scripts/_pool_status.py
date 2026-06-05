#!/usr/bin/env python3
"""Quick pool + positions snapshot."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

POOL = sys.argv[1] if len(sys.argv) > 1 else ""


def main() -> int:
    if not POOL:
        print(json.dumps({"ok": False, "error": "pool id required"}))
        return 1

    from raydium_lp1.lp_brainiac_cursor_success import build_brainiac_cursor_open_plan
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.raydium_clmm import _run_script, wallet_balance
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    load_dotenv()
    sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
    pool = fetch_pool_by_id(POOL.strip(), config=sc)
    pay = resolve_pay_mint(pool, sc)
    plan = build_brainiac_cursor_open_plan(pool, pool.get("momentum"), scanner=sc)
    wb = wallet_balance()
    chain = _run_script("list_owner_positions.mjs", {}, timeout=90)
    positions = [p for p in (chain.get("positions") or []) if str(p.get("pool_id")) == POOL.strip()]
    bp = plan.get("brainiac_placement") or {}
    out = {
        "ok": True,
        "pool_id": POOL.strip(),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "pay_type": pay.pay_symbol if pay else None,
        "non_pay": pay.alt_symbol if pay else None,
        "pool_stats": {
            "liquidity_usd": pool.get("liquidity_usd"),
            "apr": pool.get("apr"),
            "fee_24h_usd": pool.get("fee_24h_usd"),
            "price": pool.get("price"),
        },
        "brainiac_placement_now": {
            "skew": plan.get("skew"),
            "tick_lower_pct_below": plan.get("tick_lower_pct_below"),
            "tick_upper_pct_above": plan.get("tick_upper_pct_above"),
            "in_range_factor": bp.get("in_range_factor_at_skew"),
            "theoretical_apr_pct": (bp.get("fee_model_leader") or {}).get("theoretical_apr_pct"),
        },
        "wallet": {
            "sol": wb.get("sol_balance"),
            "usdc": wb.get("usdc_balance"),
        },
        "your_positions": positions,
        "position_count": len(positions),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
