"""Top-10 high-APR Kyber Earn pools (Base 8453 / BNB 56) + health rank by liquidity.

Kyber's own UI sort is unreliable, so we page the API ourselves, sort locally by
APR, take the top 10, then re-rank by TVL (liquidity) to surface the 3 'least
sickly' pools (real depth, not a $100 ghost pool printing fake APR).
"""
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
    url = f"{API}?{urllib.parse.urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def fnum(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def pair_label(p: dict) -> str:
    t = p.get("tokens") or []
    if len(t) >= 2:
        return f"{t[0].get('symbol','?')}/{t[1].get('symbol','?')}"
    return "?/?"


def fetch_pools(chain_id: str, max_pages: int = 15) -> list[dict]:
    pools: list[dict] = []
    for page in range(1, max_pages + 1):
        code, body = fetch({
            "chainIds": chain_id, "tag": "high_apr", "sortBy": "apr",
            "orderBy": "DESC", "page": page, "pageSize": 20,
        })
        if code != 200 or not isinstance(body, dict):
            break
        batch = body.get("data", {}).get("pools", [])
        if not batch:
            break
        pools.extend(batch)
    # de-dup + local sort
    seen, uniq = set(), []
    for p in pools:
        a = p.get("address")
        if a in seen:
            continue
        seen.add(a)
        uniq.append(p)
    uniq.sort(key=lambda p: fnum(p.get("apr")), reverse=True)
    return uniq


def row(p: dict) -> dict:
    return {
        "pair": pair_label(p),
        "apr": fnum(p.get("apr")),
        "apr7d": fnum(p.get("allApr7d")),
        "tvl": fnum(p.get("tvl")),
        "vol1d": fnum(p.get("volume1d")),
        "vol7d": fnum(p.get("volume7d")),
        "dex": p.get("exchange", "?"),
        "fee": p.get("feeTier"),
        "addr": p.get("address", ""),
    }


def main() -> None:
    print("Source: earn-service.kyberswap.com/api/v1/explorer/pools (tag=high_apr)\n")
    for name, cid in (("BASE", "8453"), ("BNB", "56")):
        pools = fetch_pools(cid)
        top10 = [row(p) for p in pools[:10]]
        print(f"{'='*78}\n{name} (chain {cid}) — scanned {len(pools)} high_apr pools\n{'='*78}")
        print(f"TOP 10 BY APR:")
        for i, r in enumerate(top10, 1):
            print(f"{i:>2}. {r['pair']:<18} APR {r['apr']:>14,.0f}%  "
                  f"TVL ${r['tvl']:>12,.0f}  vol7d ${r['vol7d']:>12,.0f}  "
                  f"{r['dex']} fee{r['fee']}")
        # health rank: most liquid of the top-10 APR set
        health = sorted(top10, key=lambda r: r["tvl"], reverse=True)[:3]
        print(f"\n  >> TOP 3 HEALTHIEST (most liquid of the top-10 APR set):")
        for i, r in enumerate(health, 1):
            print(f"  #{i} {r['pair']:<18} TVL ${r['tvl']:>12,.0f}  "
                  f"APR {r['apr']:>12,.0f}%  vol7d ${r['vol7d']:>12,.0f}")
            print(f"      pool {r['addr']}")
        print()


if __name__ == "__main__":
    main()
