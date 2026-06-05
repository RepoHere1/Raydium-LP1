"""Fetch top 5 high-APR Kyber Earn pools on Base (8453) and BNB (56)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://earn-service.kyberswap.com/api/v1/explorer/pools"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://kyberswap.com",
    "Referer": "https://kyberswap.com/earn/pools",
}


def fetch(params: dict) -> tuple[int, object]:
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{API}?{query}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def apr_value(pool: dict) -> float:
    for key in ("apr", "maxApr", "activeApr", "estPoolApr", "poolApr"):
        val = pool.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    return 0.0


def pool_address(pool: dict) -> str:
    for key in ("address", "poolAddress", "id"):
        val = pool.get(key)
        if isinstance(val, str) and val.startswith("0x"):
            return val
    return str(pool.get("address") or pool.get("poolAddress") or "")


def pair_label(pool: dict) -> str:
    t0 = pool.get("token0") or {}
    t1 = pool.get("token1") or {}
    return f"{t0.get('symbol', '?')}/{t1.get('symbol', '?')}"


def fetch_all_high_apr(chain_id: str, max_pages: int = 10) -> list[dict]:
    pools: list[dict] = []
    for page in range(1, max_pages + 1):
        code, body = fetch(
            {
                "chainIds": chain_id,
                "tag": "high_apr",
                "sortBy": "apr",
                "orderBy": "DESC",
                "page": page,
                "pageSize": 10,
            }
        )
        if code != 200 or not isinstance(body, dict):
            break
        batch = body.get("data", {}).get("pools", [])
        if not batch:
            break
        pools.extend(batch)
    pools.sort(key=apr_value, reverse=True)
    return pools


def pair_label(pool: dict) -> str:
    tokens = pool.get("tokens") or []
    if len(tokens) >= 2:
        return f"{tokens[0].get('symbol', '?')}/{tokens[1].get('symbol', '?')}"
    return "?/?"


def main() -> None:
    print("Source: https://earn-service.kyberswap.com/api/v1/explorer/pools")
    print("Filter: tag=high_apr, sortBy=apr, orderBy=DESC (Kyber Earn UI)\n")

    for chain_name, chain_id in (("Base", "8453"), ("BNB", "56")):
        pools = fetch_all_high_apr(chain_id)
        mega = [p for p in pools if apr_value(p) >= 1_000_000]
        top5 = pools[:5]
        print(f"=== {chain_name} (chainId {chain_id}) — top 5 by Est. Pool APR ===")
        print(f"Scanned {len(pools)} high_apr pools; pools with APR >= 1,000,000%: {len(mega)}")
        for i, pool in enumerate(top5, 1):
            tokens = pool.get("tokens") or []
            t0 = tokens[0].get("address", "") if tokens else ""
            t1 = tokens[1].get("address", "") if len(tokens) > 1 else ""
            print(
                f"{i}. {pair_label(pool)} | APR {apr_value(pool):,.2f}% | "
                f"TVL ~${float(pool.get('tvl') or 0):,.0f} | "
                f"pool {pool_address(pool)} | "
                f"dex {pool.get('exchange', '?')} (fee tier {pool.get('feeTier')})"
            )
            if t0 and t1:
                print(f"   tokens: {t0} / {t1}")
        print()


if __name__ == "__main__":
    main()
