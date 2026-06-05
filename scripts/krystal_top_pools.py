"""Krystal pool fetch — two routes.

ROUTE A (recommended, public/supported): Krystal Cloud
    Host:   https://cloud-api.krystal.app
    Path:   /v1/pools
    Auth:   header  KC-APIKey: <your key>   (free key from https://cloud.krystal.app)
    Params: chainId, protocol, sortBy=apr, orderBy=desc, limit, offset
    MCP:    Krystal also ships a Cloud-MCP connector (real-time pools/positions
            inside Claude Desktop) if you'd rather not hand-roll HTTP.

ROUTE B (internal, used by defi.krystal.app frontend — currently gated):
    Host:   https://api.krystal.app
    Path:   /all/v1/lp_explorer/top_pools?chainId=<id>
    Note:   As of this run it returns 'chain id <x> not supported' for EVERY
            chain (incl. 1/Ethereum) even though /lp_explorer/configs lists
            1,10,56,137,8453,42161,43114,80094,999 as supported. So the public
            unauthenticated path is broken/gated server-side right now — same
            class of 'Kyber sort is screwed up' jank. Helper endpoints that DO
            work unauthenticated:
              /all/v1/lp_explorer/configs       -> supported chains + protocols
              /all/v1/lp_explorer/pool_detail   ?chainId&protocol&poolAddress
              /all/v1/lp_explorer/pool_chart
"""
from __future__ import annotations
import json, os, urllib.parse, urllib.request, urllib.error

CLOUD = "https://cloud-api.krystal.app/v1/pools"


def cloud_pools(chain_id: int, api_key: str, limit: int = 10) -> object:
    params = {"chainId": chain_id, "sortBy": "apr", "orderBy": "desc", "limit": limit}
    url = f"{CLOUD}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "KC-APIKey": api_key,
        "User-Agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def configs() -> object:
    url = "https://api.krystal.app/all/v1/lp_explorer/configs"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    key = os.environ.get("KRYSTAL_API_KEY", "")
    if key:
        for cid in (8453, 56):
            print(f"chain {cid}:", json.dumps(cloud_pools(cid, key, 10))[:400])
    else:
        print("Set KRYSTAL_API_KEY (free at https://cloud.krystal.app) to pull pools.")
        print("Supported chains (live):",
              list(configs().get("data", {}).get("chains", {}).keys()))
