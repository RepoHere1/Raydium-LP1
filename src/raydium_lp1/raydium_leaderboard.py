"""
raydium_leaderboard v1.0 — scrape top wallets from Raydium perps leaderboard.

Target: https://perps.raydium.io/leaderboard (top 1000 wallets, optionally
ranked by win-rate).

CAVEATS (read first):
  - perps.raydium.io is a React/Vite app — the leaderboard renders
    client-side. urllib alone gets you a JS shell, NOT the data.
  - Two practical paths:
      Path A (this module): probe the backing API directly. Raydium's perps
              are hosted by Flash.Trade — try their public-ish API.
              Will work if Flash.Trade exposes a public leaderboard endpoint.
      Path B (fallback): use Chrome via mcp/Playwright to render the page,
              then extract the wallet list from the DOM. Requires a separate
              `raydium_leaderboard_chrome.py` that we don't ship here.

Output: kalshi-style — top N wallets ranked by win-rate (with a min-trades
filter to filter out 1-trade 100%-winners). Written to:
  raydium_leaderboard.json

Usage:
  py -3 -m raydium_lp1.raydium_leaderboard            # top 100
  py -3 -m raydium_lp1.raydium_leaderboard 1000       # top 1000
  py -3 -m raydium_lp1.raydium_leaderboard 1000 rodeo # also write to settings

Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = REPO / "raydium_leaderboard.json"
SETTINGS_PATH = REPO / "settings.json"

# Candidate API bases — Flash.Trade hosts Raydium's perps backend.
# We try in order and the first that returns parseable data wins.
CANDIDATE_BASES = [
    "https://api.flash.trade",
    "https://api2.flash.trade",
    "https://perps-api.raydium.io",
    "https://api.raydium.io/perps",
]

CANDIDATE_PATHS = [
    "/leaderboard",
    "/v1/leaderboard",
    "/v2/leaderboard",
    "/api/leaderboard",
    "/traders/leaderboard",
    "/rankings",
]

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin":          "https://perps.raydium.io",
    "Referer":         "https://perps.raydium.io/leaderboard",
}


def _http_get(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _try_endpoints(limit: int, sort: str = "winRate") -> tuple[list, str]:
    qs = urllib.parse.urlencode({"limit": limit, "sort": sort, "order": "desc"})
    for base in CANDIDATE_BASES:
        for path in CANDIDATE_PATHS:
            url = f"{base}{path}?{qs}"
            body = _http_get(url)
            if body is None:
                continue
            rows = None
            if isinstance(body, list):
                rows = body
            elif isinstance(body, dict):
                for key in ("leaderboard", "data", "traders", "rankings",
                            "results", "items", "users"):
                    v = body.get(key)
                    if isinstance(v, list):
                        rows = v
                        break
                    if isinstance(v, dict):
                        for nested_key in ("rows", "list", "items"):
                            if isinstance(v.get(nested_key), list):
                                rows = v[nested_key]
                                break
            if rows is not None:
                return rows, url
    return [], ""


def _normalize(raw: dict, rank: int) -> dict:
    def g(*keys, default=None):
        for k in keys:
            v = raw.get(k)
            if v is not None: return v
        return default

    win_rate_raw = g("winRate", "win_rate", "wr", default=0)
    try:
        wr = float(win_rate_raw)
        win_rate_pct = wr * 100 if wr <= 1.0 else wr
    except Exception:
        win_rate_pct = 0.0

    return {
        "rank":           rank,
        "wallet":         str(g("wallet", "address", "owner", "user", default="")),
        "username":       str(g("username", "displayName", "name", default="")),
        "win_rate_pct":   round(win_rate_pct, 2),
        "profit_usd":     float(g("profitUsd", "profit", "pnl", "netProfit", default=0)),
        "volume_usd":     float(g("volumeUsd", "volume", "totalVolume", default=0)),
        "trades":         int(g("trades", "tradeCount", "totalTrades", default=0)),
        "raw":            raw,
    }


def fetch_top(top_n: int = 100, min_trades: int = 20,
              min_win_rate_pct: float = 55.0) -> dict:
    rows, source = _try_endpoints(top_n)
    if not rows:
        rows, source = _try_endpoints(top_n, sort="profit")
    if not rows:
        return {
            "ok":     False,
            "error":  "all leaderboard endpoints failed. perps.raydium.io is "
                      "Vite-rendered; the backing API is likely auth-gated or "
                      "uses GraphQL. Fallback: render via Chrome and extract DOM.",
            "tried":  [f"{b}{p}" for b in CANDIDATE_BASES for p in CANDIDATE_PATHS],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    leaders = []
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            continue
        norm = _normalize(raw, len(leaders) + 1)
        if norm["trades"] < min_trades:    continue
        if norm["win_rate_pct"] < min_win_rate_pct: continue
        if not norm["wallet"]:             continue
        leaders.append(norm)

    leaders.sort(key=lambda r: (-r["win_rate_pct"], -r["volume_usd"]))
    leaders = leaders[:top_n]
    for i, r in enumerate(leaders): r["rank"] = i + 1

    return {
        "ok":         True,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source,
        "raw_count":  len(rows),
        "kept_count": len(leaders),
        "filters":    {
            "top_n":            top_n,
            "min_trades":       min_trades,
            "min_win_rate_pct": min_win_rate_pct,
        },
        "leaders":    leaders,
    }


def save_snapshot(payload: dict) -> str:
    tmp = str(OUTPUT_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, OUTPUT_PATH)
    return str(OUTPUT_PATH)


def add_to_rodeo(payload: dict) -> dict:
    """Merge top wallets into settings.json under 'raydium_rodeo_targets'."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            settings = json.load(fh)
            if not isinstance(settings, dict):
                settings = {}
    except Exception:
        settings = {}

    existing = set(settings.get("raydium_rodeo_targets") or [])
    added = 0
    for r in payload.get("leaders") or []:
        w = r.get("wallet")
        if w and w not in existing:
            existing.add(w)
            added += 1

    settings["raydium_rodeo_targets"] = sorted(existing)
    tmp = str(SETTINGS_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, sort_keys=True)
    os.replace(tmp, SETTINGS_PATH)

    return {"ok": True, "added": added, "total_in_settings": len(existing)}


def status() -> dict:
    return {
        "module":        "raydium_leaderboard",
        "output_path":   str(OUTPUT_PATH),
        "output_exists": OUTPUT_PATH.exists(),
        "output_age_s":  (time.time() - OUTPUT_PATH.stat().st_mtime)
                         if OUTPUT_PATH.exists() else None,
        "candidate_endpoints": len(CANDIDATE_BASES) * len(CANDIDATE_PATHS),
    }


if __name__ == "__main__":
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    mode  = sys.argv[2] if len(sys.argv) > 2 else "fetch"

    if mode == "status":
        print(json.dumps(status(), indent=2))
        sys.exit(0)

    print(f"[leaderboard] fetching top {top_n}…", file=sys.stderr)
    payload = fetch_top(top_n=top_n)
    if not payload.get("ok"):
        print(json.dumps(payload, indent=2))
        print("\n[NEXT STEP] all direct API endpoints failed. To get the "
              "leaderboard you'll need a Chrome-rendered scraper. Tell Claude "
              "'fall back to Chrome scraper for raydium leaderboard' if you "
              "want me to build that variant.", file=sys.stderr)
        sys.exit(1)

    path = save_snapshot(payload)
    print(f"[leaderboard] saved {payload['kept_count']} wallets to {path}", file=sys.stderr)

    if mode == "rodeo":
        merge = add_to_rodeo(payload)
        print(json.dumps(merge, indent=2))
    else:
        print(json.dumps({
            "kept_count":  payload["kept_count"],
            "raw_count":   payload["raw_count"],
            "source_url":  payload["source_url"],
            "top_5":       payload["leaders"][:5],
            "saved_to":    path,
        }, indent=2))
