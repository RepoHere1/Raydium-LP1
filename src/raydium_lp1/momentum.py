"""Short-term LP momentum scoring from live Raydium metrics.

Translates “where fee volume is *now* and whether it is *accelerating*” into a
0–100 score using only data we already pull from Raydium (TVL, 24h/7d volume,
APR, pool age, fees) plus optional health history for **exit-now** hints.

This does not predict the future; it ranks pools that currently look like
active buyer attention is flowing through the AMM so LP fee capture is plausible
for roughly a 1-day to 1-week hold — then flags when live data says leave.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

HOLD_1D_HOURS = 24.0
HOLD_1W_HOURS = 168.0

TIER_HOT = "hot"
TIER_ENTER = "enter_bias"
TIER_WATCH = "watch"
TIER_EXIT = "exit_now"


@dataclass(frozen=True)
class MomentumConfig:
    """Thresholds for momentum scoring (from ScannerConfig / settings.json)."""

    enabled: bool = False
    min_score: float = 0.0
    require_min_score: bool = False
    hold_hours: float = HOLD_1D_HOURS
    min_volume_tvl_ratio: float = 0.25
    sweet_min_pool_age_hours: float = 6.0
    sweet_max_pool_age_hours: float = 168.0
    min_tvl_usd: float = 0.0  # 0 = use scanner min_liquidity_usd only


@dataclass
class MomentumAssessment:
    score: float
    tier: str
    signals: list[str] = field(default_factory=list)
    exit_watch: bool = False
    exit_reasons: list[str] = field(default_factory=list)
    hold_hint_hours: float = HOLD_1D_HOURS
    volume_tvl_ratio: float = 0.0
    volume_accel: float = 0.0
    fee_24h_usd: float = 0.0
    pool_age_hours: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "tier": self.tier,
            "signals": list(self.signals),
            "exit_watch": self.exit_watch,
            "exit_reasons": list(self.exit_reasons),
            "hold_hint_hours": self.hold_hint_hours,
            "volume_tvl_ratio": round(self.volume_tvl_ratio, 3),
            "volume_accel": round(self.volume_accel, 3),
            "fee_24h_usd": round(self.fee_24h_usd, 2),
            "pool_age_hours": self.pool_age_hours,
        }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def pool_age_hours(pool: Mapping[str, Any], *, now: float | None = None) -> float | None:
    open_time = float(pool.get("open_time") or 0)
    if open_time <= 0:
        return None
    ts = now if now is not None else time.time()
    return max(0.0, (ts - open_time) / 3600.0)


def volume_week_usd(pool: Mapping[str, Any]) -> float:
    raw = pool.get("raw")
    if isinstance(raw, dict):
        week = raw.get("week")
        if isinstance(week, dict):
            return float(week.get("volume") or 0)
    return float(pool.get("volume_7d_usd") or 0)


def volume_accel_ratio(pool: Mapping[str, Any]) -> float:
    """>1 means 24h volume pace exceeds the trailing 7d daily average."""

    vol_day = float(pool.get("volume_24h_usd") or 0)
    vol_week = volume_week_usd(pool)
    if vol_week <= 0:
        return 1.0 if vol_day > 0 else 0.0
    daily_avg = vol_week / 7.0
    if daily_avg <= 0:
        return 0.0
    return vol_day / daily_avg


def assess_momentum(
    pool: Mapping[str, Any],
    cfg: MomentumConfig,
    *,
    health: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> MomentumAssessment:
    """Score one normalized pool dict using live Raydium fields."""

    tvl = float(pool.get("liquidity_usd") or 0)
    vol24 = float(pool.get("volume_24h_usd") or 0)
    apr = float(pool.get("apr") or 0)
    fee24 = float(pool.get("fee_24h_usd") or 0)
    vol_tvl = (vol24 / tvl) if tvl > 0 else 0.0
    accel = volume_accel_ratio(pool)
    age_h = pool_age_hours(pool, now=now)
    hold = float(cfg.hold_hours) if cfg.hold_hours > 0 else HOLD_1D_HOURS

    signals: list[str] = []
    exit_reasons: list[str] = []
    score = 0.0

    # --- Exit-first (health / illiquidity) ---
    if health:
        h_score = str(health.get("score") or "")
        if h_score == "critical":
            exit_reasons.append("health critical: " + "; ".join(health.get("reasons") or [])[:120])
        elif h_score == "warning":
            signals.append("health_warning")

    min_tvl = float(cfg.min_tvl_usd) if cfg.min_tvl_usd > 0 else 0.0
    if min_tvl > 0 and tvl < min_tvl:
        exit_reasons.append(f"TVL ${tvl:.2f} below momentum floor ${min_tvl:.2f}")

    if tvl > 0 and vol24 < 50:
        exit_reasons.append("24h volume near zero — buyers not trading through pool")

    if exit_reasons:
        return MomentumAssessment(
            score=0.0,
            tier=TIER_EXIT,
            signals=signals,
            exit_watch=True,
            exit_reasons=exit_reasons,
            hold_hint_hours=hold,
            volume_tvl_ratio=vol_tvl,
            volume_accel=accel,
            fee_24h_usd=fee24,
            pool_age_hours=age_h,
        )

    # --- Positive scoring (0–100) ---
    # Real LP depth (log-scaled TVL up to ~$50k+)
    if tvl >= 50_000:
        score += 25.0
        signals.append("tvl_deep")
    elif tvl >= 10_000:
        score += 20.0
        signals.append("tvl_solid")
    elif tvl >= 2_000:
        score += 14.0
        signals.append("tvl_lp_ok")
    elif tvl >= 500:
        score += 8.0
    else:
        score += 3.0
        signals.append("tvl_thin")

    # Capital velocity: volume turning over against TVL
    if vol_tvl >= 5.0:
        score += 25.0
        signals.append("vol_tvl_extreme")
    elif vol_tvl >= 2.0:
        score += 20.0
        signals.append("vol_tvl_high")
    elif vol_tvl >= cfg.min_volume_tvl_ratio:
        score += 14.0
        signals.append("vol_tvl_ok")
    elif vol_tvl >= 0.1:
        score += 6.0
    else:
        signals.append("vol_tvl_low")

    # APR (fee yield signal; cap so 90000% dust does not dominate alone)
    apr_pts = _clamp(apr / 80.0, 0.0, 25.0)
    score += apr_pts
    if apr >= 500:
        signals.append("apr_high")
    if apr >= 2000:
        signals.append("apr_extreme")

    # Acceleration: today hotter than 7d average
    if accel >= 2.5:
        score += 20.0
        signals.append("volume_surging")
    elif accel >= 1.35:
        score += 14.0
        signals.append("volume_accelerating")
    elif accel >= 1.0:
        score += 8.0
    elif accel < 0.6 and vol24 > 100:
        score -= 5.0
        signals.append("volume_fading")

    # Age sweet spot (meme run window)
    if age_h is not None:
        if cfg.sweet_min_pool_age_hours <= age_h <= cfg.sweet_max_pool_age_hours:
            score += 10.0
            signals.append("age_hype_window")
        elif age_h < cfg.sweet_min_pool_age_hours:
            score += 2.0
            signals.append("age_very_new")
        else:
            score += 4.0
            signals.append("age_mature")

    # Fees actually being paid (USD)
    if fee24 >= 100:
        score += 8.0
        signals.append("fees_strong")
    elif fee24 >= 10:
        score += 4.0
        signals.append("fees_present")

    score = _clamp(score, 0.0, 100.0)

    tier = TIER_WATCH
    if score >= 72 and vol_tvl >= cfg.min_volume_tvl_ratio and apr >= 200:
        tier = TIER_HOT
    elif score >= 55:
        tier = TIER_ENTER
    elif score < 35:
        tier = TIER_WATCH

    if health and str(health.get("score")) == "warning" and tier == TIER_HOT:
        tier = TIER_ENTER
        exit_reasons.append("health warning — consider exit if TVL/volume slip")

    exit_watch = bool(exit_reasons) or tier == TIER_EXIT

    return MomentumAssessment(
        score=score,
        tier=tier,
        signals=signals,
        exit_watch=exit_watch,
        exit_reasons=exit_reasons,
        hold_hint_hours=hold,
        volume_tvl_ratio=vol_tvl,
        volume_accel=accel,
        fee_24h_usd=fee24,
        pool_age_hours=age_h,
    )


def momentum_config_from_scanner(config: Any) -> MomentumConfig:
    """Build :class:`MomentumConfig` from a :class:`ScannerConfig` instance."""

    return MomentumConfig(
        enabled=bool(getattr(config, "momentum_enabled", False)),
        min_score=float(getattr(config, "min_momentum_score", 0.0)),
        require_min_score=bool(getattr(config, "require_momentum_score", False)),
        hold_hours=float(getattr(config, "momentum_hold_hours", HOLD_1D_HOURS)),
        min_volume_tvl_ratio=float(getattr(config, "momentum_min_volume_tvl_ratio", 0.25)),
        sweet_min_pool_age_hours=float(getattr(config, "momentum_sweet_min_pool_age_hours", 6.0)),
        sweet_max_pool_age_hours=float(getattr(config, "momentum_sweet_max_pool_age_hours", 168.0)),
        min_tvl_usd=float(getattr(config, "momentum_min_tvl_usd", 0.0)),
    )


def gate_candidate(
    pool: Mapping[str, Any],
    assessment: MomentumAssessment,
    cfg: MomentumConfig,
) -> tuple[bool, list[str]]:
    """Optional hard gate when ``require_min_score`` is enabled."""

    if not cfg.enabled or not cfg.require_min_score:
        return True, []
    if assessment.tier == TIER_EXIT:
        return False, list(assessment.exit_reasons) or ["momentum exit_now"]
    if assessment.score < cfg.min_score:
        return False, [
            f"momentum score {assessment.score:.0f} below min {cfg.min_score:.0f} "
            f"(vol/tvl={assessment.volume_tvl_ratio:.2f}, accel={assessment.volume_accel:.2f})"
        ]
    return True, []


def format_momentum_brief(assessment: MomentumAssessment) -> str:
    """One-line summary for console / CSV."""

    tag = assessment.tier.upper()
    return (
        f"MOM={assessment.score:.0f} {tag} "
        f"vol/tvl={assessment.volume_tvl_ratio:.1f} accel={assessment.volume_accel:.1f}x"
    )
