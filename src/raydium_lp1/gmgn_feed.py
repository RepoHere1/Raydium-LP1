"""Live leaderboard feed for the GMGN copy-trading venue.

Faithful port of FutureGMGN's futurefun_scouter — pulls the real Future.fun
trader leaderboard (https://app.future.fun/api/traders, paginated), normalises
it, drops low-sample wallets, and ranks by weighted_win_rate so a 100%-over-3-day
wallet can't outrank a 95%-over-300-day wallet.

Output rows are shaped as orchestrator/gmgn_venue candidate dicts:
    {address, username, win_rate, tracked_days, tx_count_1h, score, rank,
     total_pnl_usd, sharpe, profit_factor, max_dd_pct, daily_volatility_pct,
     market_id, market, entry_price_cents, current_spread_cents, hours_remaining}

NOTE: /api/traders gives wallet QUALITY, not the specific market a wallet just
entered. The market_* / entry_* / hours_remaining fields are therefore left at
neutral defaults here — wire a positions feed (Polymarket CLOB) to populate them
for true trade mirroring. As-is this produces a ranked, quality-gated WATCHLIST
that the gamble_scrubber + Kelly sizer act on.

Config keys (all under the venue cfg dict):
  gmgn_feed_base            (str, default https://app.future.fun)
  gmgn_feed_max_traders     (int, default 300)
  gmgn_feed_min_tracked_days(int, default 7)
  gmgn_feed_rank_by         (str, default weighted_win_rate)
  gmgn_feed_top_n           (int, default 25)  -> how many candidates to emit
  gmgn_feed_min_profit_factor(float, default 0) -> optional quality gate
  gmgn_feed_max_dd_pct      (float, default 100) -> optional max drawdown gate
  gmgn_feed_timeout         (float, default 8.0)
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

DEFAULT_BASE = "https://app.future.fun"
TRADERS_PATH = "/api/traders"
USER_AGENT = "QuantumLogic/2.7 (+local; browser-wallet-only)"
PAGE_LIMIT_MAX = 100
WEIGHTING_TARGET_DAYS = 30


def _fetch_page(base: str, page: int, limit: int, timeout: float) -> dict | None:
    url = f"{base.rstrip('/')}{TRADERS_PATH}?page={page}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and "traders" in data:
            return data
    except Exception:
        return None
    return None


def _fetch_all(base: str, max_traders: int, timeout: float) -> list[dict]:
    out: list[dict] = []
    page = 1
    while len(out) < max_traders:
        limit = min(max_traders - len(out), PAGE_LIMIT_MAX)
        data = _fetch_page(base, page, limit, timeout)
        if not data:
            break
        batch = data.get("traders") or []
        if not batch:
            break
        out.extend(batch)
        if not (data.get("pagination") or {}).get("hasNext"):
            break
        page += 1
    return out[:max_traders]


def _weighted(win_rate: float, tracked_days: int) -> float:
    return round(win_rate * min(1.0, tracked_days / float(WEIGHTING_TARGET_DAYS)), 2)


def _normalise(t: dict) -> dict | None:
    if not isinstance(t, dict):
        return None
    try:
        tracked = max(int(t.get("trackedDays") or 0), 0)
        wins = int(t.get("winDays") or 0)
        win_rate = (wins / tracked * 100.0) if tracked > 0 else 0.0
        return {
            "address": str(t.get("walletAddress") or t.get("traderId") or ""),
            "username": str(t.get("traderName") or "")[:32],
            "win_rate": round(win_rate, 2),
            "weighted_win_rate": _weighted(win_rate, tracked),
            "tracked_days": tracked,
            "win_days": wins,
            "loss_days": int(t.get("lossDays") or 0),
            "tx_count_1h": 0,  # not in leaderboard payload; positions feed fills this
            "score": int(t.get("score") or 0),
            "rank": int(t.get("rank") or 0),
            "total_pnl_usd": round(float(t.get("pnlTrackedPeriod") or t.get("pnlAllTime") or 0), 2),
            "sharpe": float(t.get("sharpeRatio") or 0),
            "profit_factor": float(t.get("profitFactor") or 0),
            "max_dd_pct": float(t.get("maxDailyDrawdownPercentage") or 0),
            "daily_volatility_pct": float(t.get("dailyVolatilityPercentage") or 0),
            # market signal fields — neutral until a positions feed is wired:
            "market_id": "", "market": str(t.get("traderName") or "")[:32] or "WATCHLIST",
            "entry_price_cents": 50.0, "current_spread_cents": 0.0, "hours_remaining": 24.0,
            "_source": "future.fun.live",
        }
    except Exception:
        return None


def fetch_leaderboard(cfg: dict | None = None) -> list[dict]:
    """Live Future.fun leaderboard as venue candidate dicts (ranked, quality-gated)."""
    cfg = cfg or {}
    base = str(cfg.get("gmgn_feed_base", DEFAULT_BASE))
    max_traders = int(cfg.get("gmgn_feed_max_traders", 300))
    min_days = int(cfg.get("gmgn_feed_min_tracked_days", 7))
    rank_by = str(cfg.get("gmgn_feed_rank_by", "weighted_win_rate"))
    top_n = int(cfg.get("gmgn_feed_top_n", 25))
    min_pf = float(cfg.get("gmgn_feed_min_profit_factor", 0.0))
    max_dd = float(cfg.get("gmgn_feed_max_dd_pct", 100.0))
    timeout = float(cfg.get("gmgn_feed_timeout", 8.0))

    raw = _fetch_all(base, max_traders, timeout)
    rows = [r for r in (_normalise(t) for t in raw) if r]
    rows = [r for r in rows if r["tracked_days"] >= min_days
            and r["profit_factor"] >= min_pf and r["max_dd_pct"] <= max_dd]
    key = {
        "score": lambda r: -r["score"],
        "win_rate": lambda r: -r["win_rate"],
        "weighted_win_rate": lambda r: -r["weighted_win_rate"],
        "pnl": lambda r: -r["total_pnl_usd"],
        "sharpe": lambda r: -r["sharpe"],
    }.get(rank_by, lambda r: -r["weighted_win_rate"])
    rows.sort(key=key)
    return rows[:top_n]


if __name__ == "__main__":
    import sys
    cfg = {"gmgn_feed_max_traders": int(sys.argv[1]) if len(sys.argv) > 1 else 100,
           "gmgn_feed_top_n": 8}
    t0 = time.time()
    rows = fetch_leaderboard(cfg)
    print(f"fetched top {len(rows)} in {time.time()-t0:.1f}s\n")
    for r in rows:
        print(f"  #{r['rank']:<4} {r['address'][:12]}… wwr={r['weighted_win_rate']:5.1f} "
              f"raw={r['win_rate']:5.1f}% {r['tracked_days']}d PF={r['profit_factor']:.2f} "
              f"DD={r['max_dd_pct']:.1f}% pnl=${r['total_pnl_usd']:,.0f}")
