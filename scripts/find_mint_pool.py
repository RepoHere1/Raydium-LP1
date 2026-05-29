"""Find Raydium CLMM pools for a mint; rank by filters + sellability."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    from raydium_lp1 import routes
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.scanner import ScannerConfig, fetch_json, filter_pool, load_dotenv, normalize_pool

    parser = argparse.ArgumentParser()
    parser.add_argument("mint", help="Token mint to match")
    parser.add_argument("--quote", default="SOL", help="Prefer quote symbol (SOL/USDC/USDT)")
    args = parser.parse_args()

    load_dotenv()
    config = ScannerConfig.from_file(REPO / "config" / "settings.json")
    mint = args.mint.strip()
    url = (
        f"{config.raydium_api_base.rstrip('/')}/pools/info/mint"
        f"?mint1={mint}&poolType=concentrated&poolSortField=liquidity&sortType=desc&pageSize=20&page=1"
    )
    payload = fetch_json(url, timeout=config.http_timeout_seconds)
    block = payload.get("data") if isinstance(payload, dict) else {}
    items = block.get("data") if isinstance(block, dict) else block
    if not isinstance(items, list):
        items = []

    ranked: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        pool = normalize_pool(raw, config.apr_field)
        if mint not in {pool.get("mint_a"), pool.get("mint_b")}:
            continue
        ok, reasons = filter_pool(pool, config)
        sell = routes.check_pool_sellability(
            pool,
            base_symbols=tuple(sorted(config.allowed_quote_symbols)),
            sources=config.route_sources,
            max_route_price_impact_pct=config.max_route_price_impact_pct or 0.0,
        )
        ranked.append(
            {
                "pool_id": pool.get("id"),
                "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
                "apr": pool.get("apr"),
                "liquidity_usd": pool.get("liquidity_usd"),
                "volume_24h_usd": pool.get("volume_24h_usd"),
                "filter_pass": ok,
                "filter_reasons": reasons,
                "sell_ok": sell.ok,
                "sellability": sell.to_dict(),
            }
        )

    def _key(row: dict) -> tuple:
        return (
            1 if row.get("filter_pass") and row.get("sell_ok") else 0,
            float(row.get("liquidity_usd") or 0),
            float(row.get("apr") or 0),
        )

    ranked.sort(key=_key, reverse=True)
    print(json.dumps({"mint": mint, "pools": ranked}, indent=2))
    if ranked:
        best = ranked[0]
        print("\nBEST:", best["pool_id"], best["pair"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
