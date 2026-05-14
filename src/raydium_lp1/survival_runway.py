"""SurvivalRunwayFilter: keep the highest-APR pools that look like they can keep paying.

The name to remember is **survival_runway**.

What it asks, in plain English:
- If I open a position here today, will the pool still be a live, active market
  3 to 7 days from now? Or is it about to dry up into a $0 ghost?

It is a *heuristic* on the public Raydium pool data, not a guarantee. It does
three cheap checks against the snapshot the scanner already pulled:

1. The pool's TVL is at least `min_tvl_multiple_of_position` times your future
   `max_position_usd`. A $25 position into a $25 pool is the same as the pool
   collapsing the moment you enter.
2. The pool's 24h volume divided by its TVL meets `min_daily_volume_pct_of_tvl`.
   If a pool churns its TVL multiple times per day, fee income is feeding back
   into the LP; if 24h volume is only 0.01% of TVL, fees can't sustain LPs and
   APR is probably a one-day mirage.
3. (optional) The pool already has nonzero weekly volume, i.e. it didn't
   appear ten minutes ago. This screens "pool created at 10:55, top APR by
   11:05, rugged by 11:30" pools when `require_active_week` is on.

Settings live under `survival_runway` in `config/settings.json`. See SETTINGS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SurvivalRunwayConfig:
    enabled: bool = True
    target_survival_days: float = 5.0
    min_tvl_multiple_of_position: float = 200.0
    min_daily_volume_pct_of_tvl: float = 5.0
    require_active_week: bool = True

    @classmethod
    def from_raw(cls, raw: Any) -> "SurvivalRunwayConfig":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            target_survival_days=float(raw.get("target_survival_days", cls.target_survival_days)),
            min_tvl_multiple_of_position=float(
                raw.get("min_tvl_multiple_of_position", cls.min_tvl_multiple_of_position)
            ),
            min_daily_volume_pct_of_tvl=float(
                raw.get("min_daily_volume_pct_of_tvl", cls.min_daily_volume_pct_of_tvl)
            ),
            require_active_week=bool(raw.get("require_active_week", cls.require_active_week)),
        )


def evaluate_survival_runway(
    pool: dict[str, Any],
    config: SurvivalRunwayConfig,
    max_position_usd: float,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails)."""

    if not config.enabled:
        return True, None

    tvl = float(pool.get("liquidity_usd") or 0.0)
    vol_24h = float(pool.get("volume_24h_usd") or 0.0)

    required_tvl = max_position_usd * config.min_tvl_multiple_of_position
    if tvl < required_tvl:
        return False, (
            f"tvl ${tvl:,.0f} below survival floor "
            f"(need >= ${required_tvl:,.0f} = {config.min_tvl_multiple_of_position:g}x position "
            f"to survive ~{config.target_survival_days:g} days)"
        )

    daily_ratio_pct = (vol_24h / tvl) * 100.0 if tvl > 0 else 0.0
    if daily_ratio_pct < config.min_daily_volume_pct_of_tvl:
        return False, (
            f"24h vol/TVL {daily_ratio_pct:.2f}% below {config.min_daily_volume_pct_of_tvl:.2f}% "
            f"(pool fees probably won't carry a {config.target_survival_days:g}-day LP)"
        )

    if config.require_active_week:
        raw = pool.get("raw") or {}
        week = raw.get("week") if isinstance(raw, dict) else None
        weekly_volume = 0.0
        if isinstance(week, dict):
            weekly_volume = float(week.get("volume") or 0.0)
        if weekly_volume <= 0.0:
            return False, "no weekly volume yet (pool too new or inactive for survival check)"

    return True, None
