"""Positions/activity feed — turns the leaderboard watchlist into GENUINE copy
trades by reading what each trusted wallet actually just bought.

Faithful port of FutureGMGN's polymarket_feed (data-api.polymarket.com). The
Future.fun leaderboard wallets are Polymarket proxy wallets, so:

    gmgn_feed.fetch_leaderboard  -> WHICH wallets to trust (win-rate, tracked days)
    THIS module                  -> WHAT each trusted wallet just bought (the signal)

For each top wallet we pull recent TRADE activity, take the latest fresh BUY,
and emit a candidate carrying both the wallet's quality AND the live market
signal (entry price, freshness, tilt). The gamble_scrubber + Kelly sizer in
gmgn_venue then act on a REAL trade, not a neutral placeholder.

Endpoints (keyless):
  GET https://data-api.polymarket.com/activity?user=<addr>&limit=N
  GET https://data-api.polymarket.com/value?user=<addr>     (portfolio USD)
  GET https://gamma-api.polymarket.com/markets?condition_ids=<cid>  (liquidity, endDate)

Config keys:
  gmgn_signal_only_side       (str, default 'BUY')     -> mirror buys only
  gmgn_signal_max_age_min     (int, default 60)        -> ignore stale trades
  gmgn_signal_activity_limit  (int, default 20)
  gmgn_signal_enrich_market   (bool, default True)     -> pull liquidity + hours_remaining
  gmgn_signal_timeout         (float, default 8.0)
  (plus all gmgn_feed_* keys, since this calls the leaderboard first)
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

_MKT_CACHE: dict[str, tuple[float, dict]] = {}   # condition_id -> (ts, {liq, end_ts})
_MKT_TTL = 300


def _http_get(url: str, timeout: float = 8.0):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "QuantumLogic/2.7 (+local; browser-wallet-only)",
            "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def fetch_activity(wallet: str, limit: int = 20, timeout: float = 8.0) -> list[dict]:
    if not wallet:
        return []
    raw = _http_get(f"{DATA_API}/activity?user={wallet}&limit={limit}", timeout=timeout)
    return raw if isinstance(raw, list) else []


def fetch_value(wallet: str, timeout: float = 8.0) -> float:
    raw = _http_get(f"{DATA_API}/value?user={wallet}", timeout=timeout)
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        try:
            return float(raw[0].get("value") or 0)
        except Exception:
            return 0.0
    return 0.0


def fetch_market_meta(condition_id: str, timeout: float = 6.0) -> dict:
    """Real liquidity (USD) + end timestamp for a market, cached 5 min."""
    if not condition_id:
        return {"liquidity_usd": 0.0, "end_ts": 0}
    now = time.time()
    cached = _MKT_CACHE.get(condition_id)
    if cached and (now - cached[0]) < _MKT_TTL:
        return cached[1]
    raw = _http_get(f"{GAMMA_API}/markets?condition_ids={condition_id}", timeout=timeout)
    meta = {"liquidity_usd": 0.0, "end_ts": 0}
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        m = raw[0]
        try:
            meta["liquidity_usd"] = float(m.get("liquidityNum") or m.get("liquidity") or 0)
        except Exception:
            pass
        end_iso = str(m.get("endDate") or m.get("end_date_iso") or "")
        if end_iso:
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
                try:
                    meta["end_ts"] = int(time.mktime(time.strptime(end_iso, fmt)))
                    break
                except (ValueError, OverflowError):
                    continue
    _MKT_CACHE[condition_id] = (now, meta)
    return meta


def latest_buy_signal(wallet: str, *, only_side: str = "BUY", max_age_min: int = 60,
                      activity_limit: int = 20, enrich: bool = True,
                      timeout: float = 8.0) -> dict | None:
    """Latest FRESH trade for `wallet` as a signal dict, or None.

    Adds tx_count_1h (real tilt signal) by counting TRADE events in the last hour.
    """
    side_norm = (only_side or "ANY").upper()
    trades = fetch_activity(wallet, limit=activity_limit, timeout=timeout)
    if not trades:
        return None
    now = time.time()
    cutoff = now - max_age_min * 60
    tx_1h = sum(1 for t in trades if isinstance(t, dict) and t.get("type") == "TRADE"
                and int(t.get("timestamp") or 0) >= now - 3600)

    for t in trades:
        if not isinstance(t, dict) or t.get("type") != "TRADE":
            continue
        ts = int(t.get("timestamp") or 0)
        if ts < cutoff:
            continue
        if side_norm != "ANY" and str(t.get("side", "")).upper() != side_norm:
            continue
        price = float(t.get("price") or 0)
        cid = str(t.get("conditionId") or "")
        hours_remaining = 24.0
        liquidity = 0.0
        if enrich and cid:
            meta = fetch_market_meta(cid, timeout=timeout)
            liquidity = meta["liquidity_usd"]
            if meta["end_ts"] > 0:
                hours_remaining = max(0.0, (meta["end_ts"] - now) / 3600.0)
        return {
            "market_id": cid,
            "market": str(t.get("title") or "untitled"),
            "outcome": str(t.get("outcome") or ""),
            "entry_price_cents": round(price * 100, 2),
            "current_spread_cents": 0.5,
            "hours_remaining": round(hours_remaining, 2),
            "pool_liquidity_usd": liquidity,
            "tx_count_1h": tx_1h,
            "trade_ts": ts,
            "age_min": round((now - ts) / 60.0, 1),
            "side": str(t.get("side") or ""),
            "size_usdc": float(t.get("usdcSize") or 0),
            "asset": str(t.get("asset") or ""),
            "_source": "polymarket.live",
        }
    return None


def fetch_copy_signals(cfg: dict | None = None) -> list[dict]:
    """Genuine copy-trade candidates: trusted wallets × their latest fresh buy.

    Returns only wallets that (a) clear the leaderboard quality gate AND (b) have
    a recent BUY. Each candidate merges wallet stats + live trade signal.
    """
    cfg = cfg or {}
    from raydium_lp1.gmgn_feed import fetch_leaderboard
    wallets = fetch_leaderboard(cfg)

    only_side = str(cfg.get("gmgn_signal_only_side", "BUY"))
    max_age = int(cfg.get("gmgn_signal_max_age_min", 60))
    limit = int(cfg.get("gmgn_signal_activity_limit", 20))
    enrich = bool(cfg.get("gmgn_signal_enrich_market", True))
    timeout = float(cfg.get("gmgn_signal_timeout", 8.0))

    out: list[dict] = []
    for w in wallets:
        addr = w.get("address", "")
        sig = latest_buy_signal(addr, only_side=only_side, max_age_min=max_age,
                                activity_limit=limit, enrich=enrich, timeout=timeout)
        if not sig:
            continue
        cand: dict[str, Any] = dict(w)        # wallet quality (win_rate, tracked_days...)
        cand.update(sig)                       # live signal overrides neutral placeholders
        out.append(cand)
    return out


if __name__ == "__main__":
    import sys
    cfg = {"gmgn_feed_max_traders": int(sys.argv[1]) if len(sys.argv) > 1 else 50,
           "gmgn_feed_top_n": 15, "gmgn_feed_min_tracked_days": 14,
           "gmgn_signal_max_age_min": int(sys.argv[2]) if len(sys.argv) > 2 else 1440}
    t0 = time.time()
    sigs = fetch_copy_signals(cfg)
    print(f"{len(sigs)} live copy signals in {time.time()-t0:.1f}s\n")
    for s in sigs[:15]:
        print(f"  {s['address'][:10]}… wwr={s['weighted_win_rate']:.0f} "
              f"BUY {s['outcome'][:18]:<18} @ {s['entry_price_cents']:.0f}c "
              f"age={s['age_min']:.0f}m tx1h={s['tx_count_1h']} hrs_left={s['hours_remaining']:.0f} "
              f":: {s['market'][:32]}")
