"""GMGN copy-trading venue — leaderboard wallet mirroring with logic-driven entries.

Folds FutureGMGN's copy-trading brain into the unified orchestrator. Three pure
pieces are vendored here (faithful ports, no transitive deps on the FutureGMGN
stack) so this runs inside Raydium-LP1 standalone:

  1. weighted_win_rate ranking (from data_extractor) — discounts low-sample
     wallets so a 100%-over-3-trades wallet can't outrank a 70%-over-200 wallet.
  2. quarter-Kelly sizing (from dynamic_sizer.kelly_fraction) — bet size scales
     with the source trader's edge, capped at 10% of capital. This is the
     "make gambling logic-driven / predictable" core.
  3. gamble_scrubber.scrub (from gamble_scrubber) — the "don't do something
     stupid" gate: blocks overpaying for hype, chasing tilted/spam wallets,
     fees eating the edge, theta decay near expiry, crowd-sentiment extremes.

Pipeline role: scan leaderboard -> build copy signals -> filter_copy_quality
-> gamble_scrubber -> Kelly size -> mirror decision (decision-only by default).

The leaderboard source is PLUGGABLE via cfg['gmgn_leaderboard_fn'] or by passing
leaderboard_fn to make_gmgn_venue(). Wire it to your Future.fun / GMGN / Polymarket
feed (e.g. FutureGMGN's data_extractor.fetch_leaderboard) or a static list.
"""

from __future__ import annotations

from typing import Any, Callable

from raydium_lp1.orchestrator import Venue


# --------------------------------------------------------------------------
# Vendored pure logic (ported from FutureGMGN)
# --------------------------------------------------------------------------

def weighted_win_rate(win_rate_pct: float, tracked_days: float,
                      full_weight_days: float = 30.0) -> float:
    """raw win_rate * min(1, days/full_weight_days). Low-sample wallets decay."""
    w = min(1.0, max(0.0, float(tracked_days)) / max(1.0, full_weight_days))
    return float(win_rate_pct) * w


def kelly_fraction(edge_win_pct: float, payout_ratio: float = 2.0,
                   kelly_divisor: float = 4.0) -> float:
    """Quarter-Kelly by default. f = (b*p-(1-p))/b, capped at 10% of capital."""
    p = max(0.0, min(1.0, float(edge_win_pct) / 100.0))
    b = max(0.01, float(payout_ratio))
    full_kelly = (b * p - (1.0 - p)) / b
    if full_kelly <= 0:
        return 0.0
    return min(0.10, full_kelly / max(1.0, kelly_divisor))


def estimate_net_clear_usd(entry_usd: float, expected_profit_pct: float,
                           network_fee_usd: float, venue_fee_pct: float = 0.0,
                           slippage_pct: float = 0.0) -> float:
    gross = entry_usd * (expected_profit_pct / 100.0)
    return gross - network_fee_usd - gross * (venue_fee_pct / 100.0) - gross * (slippage_pct / 100.0)


def gamble_scrub(signal: dict, target_profile: dict, config: dict) -> dict:
    """Port of gamble_scrubber.scrub — block/warn on the classic loss patterns."""
    out: dict[str, Any] = {"allow": True, "reasons_block": [], "reasons_warn": [],
                           "recommendation": "execute", "adjusted_entry_cents": None}
    trade = config.get("trade_settings", {}) or {}
    behav = config.get("behavioral_scrubber", {}) or {}
    fp = config.get("filter_protocols", {}) or {}

    entry_usd = float(trade.get("trade_size_usd", 0.5))
    min_net_clear = float(trade.get("min_net_clear_usd", 0.05))
    max_slip = float(trade.get("max_slippage_percent", 2.5))
    tilt_limit = int(behav.get("human_tilt_threshold_txs_per_hour", 15))
    recal_buffer = float(behav.get("probability_recalibration_buffer_cents", 5.0))

    entry_cents = float(signal.get("entry_price_cents", 50.0))
    spread_cents = float(signal.get("current_spread_cents", 0.0))
    hours_remaining = float(signal.get("hours_remaining", 24.0))
    win_rate = float(target_profile.get("win_rate", 0.0))
    tx_1h = int(target_profile.get("tx_count_1h", 0))

    net_clear = estimate_net_clear_usd(
        entry_usd=entry_usd, expected_profit_pct=60.0, network_fee_usd=0.02,
        slippage_pct=max(0.0, spread_cents / max(entry_cents, 1.0) * 100.0))
    out["net_clear_usd"] = round(net_clear, 4)

    if net_clear < min_net_clear:
        out["reasons_block"].append(
            f"net clear ${net_clear:.4f} below floor ${min_net_clear:.2f} after fees+spread")
    if win_rate < 80.0 and entry_cents > 75.0:
        out["reasons_warn"].append(
            f"target win-rate {win_rate:.1f}% but paying {entry_cents}c — overpaying for low-edge momentum")
        out["adjusted_entry_cents"] = max(1.0, entry_cents - 3.0)
    if tx_1h > tilt_limit:
        out["reasons_warn"].append(f"target spamming {tx_1h} tx/hr (tilt mode)")
        adj = (out["adjusted_entry_cents"] if out["adjusted_entry_cents"] is not None else entry_cents) - recal_buffer
        out["adjusted_entry_cents"] = max(1.0, adj)
    theta_min = float(fp.get("theta_min_hours", 2.0))
    if hours_remaining < theta_min:
        out["reasons_block"].append(f"only {hours_remaining:.2f}h to expiry — under theta floor {theta_min}h")
    implied_slip = (spread_cents / max(entry_cents, 1.0)) * 100.0
    if implied_slip > max_slip:
        out["reasons_block"].append(f"implied slippage {implied_slip:.2f}% > cap {max_slip}%")
    sent_max = float(fp.get("sentiment_max_pct", 92))
    if entry_cents > sent_max:
        out["reasons_block"].append(f"crowd sentiment {entry_cents}% > contrarian cap {sent_max}%")

    if out["reasons_block"]:
        out["allow"] = False
        out["recommendation"] = "BLOCK — " + "; ".join(out["reasons_block"])
    elif out["reasons_warn"]:
        out["recommendation"] = "execute-with-adjustment"
    return out


# --------------------------------------------------------------------------
# filter_suite-compatible copy-quality filter
# --------------------------------------------------------------------------

def filter_copy_quality(cand: dict, cfg: dict) -> dict:
    """Reject signals from wallets that aren't proven enough to copy.
    Uses weighted_win_rate so low-sample wallets can't sneak through."""
    min_wwr = float(cfg.get("gmgn_min_weighted_win_rate", 55.0))
    min_days = float(cfg.get("gmgn_min_tracked_days", 7))
    win_rate = float(cand.get("win_rate", 0.0))
    days = float(cand.get("tracked_days", 0.0))
    if days < min_days:
        return {"pass": False, "reason": f"tracked {days:.0f}d < min {min_days:.0f}d"}
    wwr = weighted_win_rate(win_rate, days)
    if wwr < min_wwr:
        return {"pass": False,
                "reason": f"weighted win-rate {wwr:.1f} < min {min_wwr:.1f} "
                          f"(raw {win_rate:.0f}% over {days:.0f}d)"}
    return {"pass": True, "reason": f"weighted win-rate {wwr:.1f} ok"}


# --------------------------------------------------------------------------
# Copy-trade planner (replaces the LP skew planner for this venue)
# --------------------------------------------------------------------------

def copy_plan(cand: dict, cfg: dict) -> dict:
    """Turn a leaderboard signal into a sized, scrubbed mirror decision."""
    profile = {"win_rate": float(cand.get("win_rate", 0.0)),
               "tx_count_1h": int(cand.get("tx_count_1h", 0))}
    signal = {"entry_price_cents": float(cand.get("entry_price_cents", 50.0)),
              "current_spread_cents": float(cand.get("current_spread_cents", 0.0)),
              "hours_remaining": float(cand.get("hours_remaining", 24.0))}
    scrub = gamble_scrub(signal, profile, cfg)

    entry_cents = scrub.get("adjusted_entry_cents") or signal["entry_price_cents"]
    payout = 1.0 / max(0.01, entry_cents / 100.0)   # e.g. 50c entry -> 2x payout
    divisor = float(cfg.get("gmgn_kelly_divisor", 4.0))
    kelly_f = kelly_fraction(profile["win_rate"], payout_ratio=payout, kelly_divisor=divisor)
    wallet_usd = float(cfg.get("gmgn_wallet_usd", 0.0))
    size_usd = round(min(float(cfg.get("gmgn_max_trade_usd", 100.0)),
                         max(0.0, wallet_usd * kelly_f)), 4)

    return {
        "id": cand.get("market_id") or cand.get("id") or cand.get("token"),
        "pair": cand.get("market") or cand.get("symbol") or "?",
        "source_wallet": cand.get("address", ""),
        "win_rate": profile["win_rate"],
        "weighted_win_rate": round(weighted_win_rate(profile["win_rate"], cand.get("tracked_days", 0)), 1),
        "entry_price_cents": entry_cents,
        "kelly_fraction": round(kelly_f, 4),
        "size_usd": size_usd,
        "allow": scrub["allow"],
        "net_clear_usd": scrub.get("net_clear_usd"),
        "recommendation": scrub["recommendation"],
        "reasons_block": scrub["reasons_block"],
        "reasons_warn": scrub["reasons_warn"],
    }


# --------------------------------------------------------------------------
# Venue factory
# --------------------------------------------------------------------------

def make_gmgn_venue(leaderboard_fn: Callable[[dict], list[dict]] | None = None,
                    cfg: dict | None = None,
                    place_fn=None) -> Venue:
    """Build a copy-trading Venue. leaderboard_fn(cfg) -> list of signal dicts:
        {address, win_rate, tracked_days, tx_count_1h, market_id, market,
         entry_price_cents, current_spread_cents, hours_remaining}
    Defaults to cfg['gmgn_leaderboard_fn'] or an empty scan (refuses to fabricate).
    """
    cfg = dict(cfg or {})

    def _scan(c: dict) -> list[dict]:
        fn = leaderboard_fn or c.get("gmgn_leaderboard_fn")
        if fn is None:
            if c.get("gmgn_use_positions", True):
                # GENUINE copy-trading: trusted wallets x their latest fresh buy.
                from raydium_lp1.gmgn_positions import fetch_copy_signals as fn
            else:
                # Watchlist-only: ranked leaderboard, neutral market fields.
                from raydium_lp1.gmgn_feed import fetch_leaderboard as fn
        return list(fn(c))

    return Venue(
        name="gmgn-copy", chain_kind="copy", scan_fn=_scan, cfg=cfg,
        filters=[filter_copy_quality], plan_fn=copy_plan, place_fn=place_fn,
    )


if __name__ == "__main__":
    import json
    from raydium_lp1.orchestrator import run
    # Live GENUINE copy-trade against trusted wallets' latest fresh buys.
    v = make_gmgn_venue(cfg={
        "gmgn_min_weighted_win_rate": 70, "gmgn_min_tracked_days": 14,
        "gmgn_wallet_usd": 200.0, "gmgn_kelly_divisor": 4.0,
        "gmgn_use_positions": True,
        "gmgn_feed_max_traders": 50, "gmgn_feed_top_n": 15,
        "gmgn_signal_max_age_min": 1440,
        "trade_settings": {"trade_size_usd": 1.0, "min_net_clear_usd": 0.05,
                           "max_slippage_percent": 2.5},
        "behavioral_scrubber": {"human_tilt_threshold_txs_per_hour": 15},
        "filter_protocols": {"theta_min_hours": 2.0, "sentiment_max_pct": 92},
    })
    rep = run([v], place=False)
    ven = rep["venues"][0]
    print(json.dumps({"scanned": ven["scanned"], "passed": ven["passed"]}, indent=2))
    allow = sum(1 for p in ven["plans"] if p.get("allow"))
    print(f"allow={allow}  block={len(ven['plans'])-allow}")
    for pl in ven["plans"]:
        flag = "OK " if pl["allow"] else "BLK"
        print(f"  [{flag}] {pl['source_wallet'][:10]}.. {pl['pair'][:24]:<24} "
              f"@{pl['entry_price_cents']:.0f}c sz=${pl['size_usd']} :: {pl['recommendation'][:46]}")
