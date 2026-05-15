"""Extended momentum “sniffer” — multi-signal detective layer on live Raydium data.

Uses period objects (day / week / month), pool history, optional extra Raydium
list probes (volume leaders), and sell-route hints. Outputs sub-scores and
human-readable sniff tags. Does not predict prices; surfaces where *fee volume*
is heating up *now* vs recent baselines.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

FetchJson = Callable[[str, int], dict[str, Any]]


@dataclass
class PeriodMetrics:
    volume_usd: float = 0.0
    volume_quote: float = 0.0
    volume_fee_usd: float = 0.0
    apr: float = 0.0
    fee_apr: float = 0.0
    price_min: float = 0.0
    price_max: float = 0.0

    @property
    def price_swing_pct(self) -> float:
        if self.price_min <= 0:
            return 0.0
        return max(0.0, (self.price_max - self.price_min) / self.price_min * 100.0)


def _period_metrics(raw: Mapping[str, Any], key: str) -> PeriodMetrics:
    block = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return PeriodMetrics()
    return PeriodMetrics(
        volume_usd=float(block.get("volume") or 0),
        volume_quote=float(block.get("volumeQuote") or 0),
        volume_fee_usd=float(block.get("volumeFee") or block.get("fee") or 0),
        apr=float(block.get("apr") or 0),
        fee_apr=float(block.get("feeApr") or 0),
        price_min=float(block.get("priceMin") or 0),
        price_max=float(block.get("priceMax") or 0),
    )


def _ratio(num: float, den: float, *, default: float = 0.0) -> float:
    if den <= 0:
        return default
    return num / den


@dataclass
class DetectiveResult:
    detective_score: float
    inflow_bias: float
    sniff_tags: list[str] = field(default_factory=list)
    subscores: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    market_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detective_score": round(self.detective_score, 1),
            "inflow_bias": round(self.inflow_bias, 1),
            "sniff_tags": list(self.sniff_tags),
            "subscores": {k: round(v, 1) for k, v in self.subscores.items()},
            "metrics": {k: round(v, 4) if isinstance(v, float) else v for k, v in self.metrics.items()},
            "market_flags": list(self.market_flags),
        }


def tvl_growth_from_history(
    pool_id: str,
    history: Mapping[str, Any],
    *,
    tvl_now: float,
) -> float | None:
    """Return fractional TVL change since first snapshot in history, or None."""

    entry = history.get(pool_id) if isinstance(history, dict) else None
    if not isinstance(entry, dict):
        return None
    base = entry.get("entry") or {}
    tvl_entry = float(base.get("tvl") or 0)
    if tvl_entry <= 0:
        return None
    return (tvl_now - tvl_entry) / tvl_entry


def run_detective(
    pool: Mapping[str, Any],
    *,
    health: Mapping[str, Any] | None = None,
    history: Mapping[str, Any] | None = None,
    market_pulse: Mapping[str, set[str]] | None = None,
    now: float | None = None,
) -> DetectiveResult:
    """Compute extended momentum signals for one pool."""

    raw = pool.get("raw") if isinstance(pool.get("raw"), dict) else {}
    day = _period_metrics(raw, "day")
    week = _period_metrics(raw, "week")
    month = _period_metrics(raw, "month")

    tvl = float(pool.get("liquidity_usd") or 0)
    vol24 = float(pool.get("volume_24h_usd") or day.volume_usd)
    fee24 = float(pool.get("fee_24h_usd") or day.volume_fee_usd)
    pool_id = str(pool.get("id") or "")

    vol_tvl = _ratio(vol24, tvl)
    week_daily_vol = week.volume_usd / 7.0 if week.volume_usd > 0 else 0.0
    month_daily_vol = month.volume_usd / 30.0 if month.volume_usd > 0 else 0.0
    vol_accel_7d = _ratio(vol24, week_daily_vol, default=1.0 if vol24 > 0 else 0.0)
    vol_accel_30d = _ratio(vol24, month_daily_vol, default=1.0 if vol24 > 0 else 0.0)
    fee_accel_7d = _ratio(day.volume_fee_usd, week.volume_fee_usd / 7.0 if week.volume_fee_usd else 0)
    quote_accel_7d = _ratio(day.volume_quote, week.volume_quote / 7.0 if week.volume_quote else 0)
    apr_accel = _ratio(day.apr, week.apr if week.apr > 0 else day.apr, default=1.0)
    fee_yield_on_tvl = _ratio(fee24, tvl) * 10_000.0  # bps-style

    open_time = float(pool.get("open_time") or 0)
    ts = now if now is not None else time.time()
    age_h = (ts - open_time) / 3600.0 if open_time > 0 else None

    sniff: list[str] = []
    subs: dict[str, float] = {}
    metrics: dict[str, float] = {
        "vol_tvl": vol_tvl,
        "vol_accel_7d": vol_accel_7d,
        "vol_accel_30d": vol_accel_30d,
        "fee_accel_7d": fee_accel_7d,
        "quote_accel_7d": quote_accel_7d,
        "apr_accel": apr_accel,
        "fee_yield_bps": fee_yield_on_tvl,
        "price_swing_pct": day.price_swing_pct,
    }

    # --- Subscores (each 0–15, summed & capped) ---
    if vol_tvl >= 8:
        subs["flow_velocity"] = 15.0
        sniff.append("extreme_buyer_flow")
    elif vol_tvl >= 3:
        subs["flow_velocity"] = 12.0
        sniff.append("heavy_buyer_flow")
    elif vol_tvl >= 1:
        subs["flow_velocity"] = 8.0
        sniff.append("buyer_flow_ok")
    elif vol_tvl >= 0.3:
        subs["flow_velocity"] = 4.0
    else:
        subs["flow_velocity"] = 1.0
        sniff.append("flow_weak")

    if vol_accel_7d >= 3:
        subs["volume_surge"] = 15.0
        sniff.append("volume_surging_vs_7d")
    elif vol_accel_7d >= 1.5:
        subs["volume_surge"] = 11.0
        sniff.append("volume_accelerating")
    elif vol_accel_7d >= 1.0:
        subs["volume_surge"] = 6.0
    elif vol_accel_7d < 0.7 and vol24 > 200:
        subs["volume_surge"] = 0.0
        sniff.append("volume_fading")

    if vol_accel_30d >= 2 and vol_accel_7d >= 1.2:
        subs["monthly_heat"] = 10.0
        sniff.append("monthly_and_daily_heat")

    if fee_accel_7d >= 2:
        subs["fee_momentum"] = 12.0
        sniff.append("fees_accelerating")
    elif fee_accel_7d >= 1.2:
        subs["fee_momentum"] = 7.0
        sniff.append("fees_rising")

    if quote_accel_7d >= 1.8:
        subs["quote_leg_heat"] = 10.0
        sniff.append("quote_side_active")

    if apr_accel >= 1.5 and day.apr >= 300:
        subs["apr_expansion"] = 10.0
        sniff.append("apr_expanding")

    if day.price_swing_pct >= 15 and vol24 > 1000:
        subs["price_action"] = 8.0
        sniff.append("volatile_price_action")

    if fee_yield_on_tvl >= 50:
        subs["fee_efficiency"] = 12.0
        sniff.append("high_fee_per_tvl")
    elif fee_yield_on_tvl >= 15:
        subs["fee_efficiency"] = 6.0

    farm = int(pool.get("farm_ongoing") or 0)
    if farm > 0:
        subs["farm_rewards"] = 5.0
        sniff.append("farm_incentives_live")

    sell = pool.get("sellability") if isinstance(pool.get("sellability"), dict) else {}
    if sell.get("ok"):
        subs["exit_liquidity"] = 8.0
        sniff.append("exit_route_ok")
    elif pool.get("sellability_log"):
        subs["exit_liquidity"] = 0.0
        sniff.append("exit_route_weak")

    if history and pool_id:
        tvl_g = tvl_growth_from_history(pool_id, history, tvl_now=tvl)
        if tvl_g is not None:
            metrics["tvl_growth_since_entry"] = tvl_g
            if tvl_g >= 0.25:
                subs["tvl_growth"] = 12.0
                sniff.append("tvl_growing")
            elif tvl_g <= -0.2:
                subs["tvl_growth"] = 0.0
                sniff.append("tvl_bleeding")

    if health:
        h = str(health.get("score") or "")
        if h == "critical":
            subs["health"] = 0.0
            sniff.append("health_exit")
        elif h == "warning":
            subs["health"] = 3.0
            sniff.append("health_caution")
        else:
            subs["health"] = 6.0

    if age_h is not None:
        metrics["pool_age_hours"] = age_h
        if 6 <= age_h <= 72:
            subs["age_hype"] = 8.0
            sniff.append("fresh_hype_window")
        elif age_h < 6:
            subs["age_hype"] = 3.0
            sniff.append("brand_new_pool")

    market_flags: list[str] = []
    if market_pulse and pool_id:
        for flag, ids in market_pulse.items():
            if pool_id in ids:
                market_flags.append(flag)
                subs["market_leaderboard"] = subs.get("market_leaderboard", 0) + 5.0
        if "volume24h_leader" in market_flags:
            sniff.append("on_volume_leaderboard")
        if "apr24h_leader" in market_flags:
            sniff.append("on_apr_leaderboard")
        if "liquidity_leader" in market_flags:
            sniff.append("deep_liquidity_leader")

    detective_score = min(100.0, sum(subs.values()))

    # Inflow bias: emphasis on acceleration + flow (where money may head next)
    inflow_bias = min(
        100.0,
        vol_accel_7d * 18.0
        + min(vol_tvl, 10.0) * 6.0
        + min(fee_accel_7d, 5.0) * 8.0
        + min(quote_accel_7d, 5.0) * 5.0
        + (10.0 if "tvl_growing" in sniff else 0.0)
        + (8.0 if "on_volume_leaderboard" in sniff else 0.0),
    )

    return DetectiveResult(
        detective_score=detective_score,
        inflow_bias=inflow_bias,
        sniff_tags=sniff,
        subscores=subs,
        metrics=metrics,
        market_flags=market_flags,
    )


def fetch_market_pulse(
    api_base: str,
    *,
    page_size: int = 50,
    fetch_json: FetchJson,
    timeout: int = 15,
) -> dict[str, set[str]]:
    """Extra Raydium list pulls: top pools by volume, APR, liquidity (live)."""

    base = api_base.rstrip("/")
    sorts = (
        ("volume24h_leader", "volume24h"),
        ("apr24h_leader", "apr24h"),
        ("liquidity_leader", "liquidity"),
    )
    out: dict[str, set[str]] = {}
    for flag, sort_field in sorts:
        params = urlencode(
            {
                "poolType": "all",
                "poolSortField": sort_field,
                "sortType": "desc",
                "pageSize": min(1000, page_size),
                "page": 1,
            }
        )
        url = f"{base}/pools/info/list?{params}"
        try:
            payload = fetch_json(url, timeout)
        except (OSError, RuntimeError):
            out[flag] = set()
            continue
        data = payload.get("data", payload)
        items = []
        if isinstance(data, dict):
            items = data.get("data") or data.get("list") or []
        ids: set[str] = set()
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    ids.add(str(item["id"]))
        out[flag] = ids
    return out


def build_hot_leaderboard(
    candidates: list[dict[str, Any]],
    *,
    top_n: int = 25,
) -> list[dict[str, Any]]:
    """Top-N pools by combined momentum score for dashboard / JSON report."""

    def _rank_key(p: dict) -> float:
        mom = p.get("momentum") if isinstance(p.get("momentum"), dict) else {}
        return float(mom.get("combined_score") or mom.get("score") or 0)

    ranked = sorted(candidates, key=_rank_key, reverse=True)
    hot: list[dict[str, Any]] = []
    for pool in ranked:
        mom = pool.get("momentum") or {}
        if mom.get("tier") not in ("hot", "enter_bias") and float(mom.get("combined_score") or 0) < 55:
            continue
        hot.append(
            {
                "pool_id": pool.get("id"),
                "pair": f"{pool.get('mint_a_symbol', '')}/{pool.get('mint_b_symbol', '')}",
                "combined_score": mom.get("combined_score"),
                "score": mom.get("score"),
                "detective_score": (mom.get("detective") or {}).get("detective_score"),
                "inflow_bias": (mom.get("detective") or {}).get("inflow_bias"),
                "tier": mom.get("tier"),
                "tvl_usd": pool.get("liquidity_usd"),
                "volume_24h_usd": pool.get("volume_24h_usd"),
                "apr": pool.get("apr"),
                "sniff_tags": (mom.get("detective") or {}).get("sniff_tags", mom.get("signals", []))[:8],
                "exit_watch": mom.get("exit_watch"),
            }
        )
        if len(hot) >= top_n:
            break
    # If fewer than top_n tagged hot, fill by pure score
    if len(hot) < top_n:
        seen = {h["pool_id"] for h in hot}
        for pool in ranked:
            pid = pool.get("id")
            if pid in seen:
                continue
            mom = pool.get("momentum") or {}
            hot.append(
                {
                    "pool_id": pid,
                    "pair": f"{pool.get('mint_a_symbol', '')}/{pool.get('mint_b_symbol', '')}",
                    "combined_score": mom.get("combined_score"),
                    "score": mom.get("score"),
                    "detective_score": (mom.get("detective") or {}).get("detective_score"),
                    "inflow_bias": (mom.get("detective") or {}).get("inflow_bias"),
                    "tier": mom.get("tier"),
                    "tvl_usd": pool.get("liquidity_usd"),
                    "volume_24h_usd": pool.get("volume_24h_usd"),
                    "apr": pool.get("apr"),
                    "sniff_tags": (mom.get("detective") or {}).get("sniff_tags", [])[:8],
                    "exit_watch": mom.get("exit_watch"),
                }
            )
            if len(hot) >= top_n:
                break
    return hot
