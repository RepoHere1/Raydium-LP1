"""PoolAgeGuard: refuse pools that are too young (or too old) to enter safely.

The name to remember is **pool_age_guard**.

What it asks, in plain English:
- Was this Raydium pool created at least `min_age_minutes` ago? Sub-minute-old
  pools have no track record; in practice the top of Raydium's APR list is
  always dominated by pools that are minutes old, top out, then collapse.
- (optional) Is the pool *not* older than `max_age_days`? Some strategies
  prefer fresher pools whose fee APR hasn't been arbed down yet. Leave the
  cap at `0` (default) to disable the upper bound entirely.

How it figures out age:
1. Raydium's `/pools/info/list` payload includes `openTime` on AMM/CLMM pools
   as a unix timestamp string. We use that when present.
2. Falls back to nested `day`/`week` window summaries (`day.startTime`) when
   `openTime` is missing.
3. If no creation time can be found at all, the guard's behavior is controlled
   by `fail_open_when_unknown`. Default is **False** (= reject), which is the
   safer setting for a high-APR sniper.

Settings live under `pool_age_guard` in `config/settings.json`. See SETTINGS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class PoolAgeGuardConfig:
    enabled: bool = True
    min_age_minutes: float = 60.0
    max_age_days: float = 0.0
    fail_open_when_unknown: bool = False

    @classmethod
    def from_raw(cls, raw: Any) -> "PoolAgeGuardConfig":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            min_age_minutes=float(raw.get("min_age_minutes", cls.min_age_minutes)),
            max_age_days=float(raw.get("max_age_days", cls.max_age_days)),
            fail_open_when_unknown=bool(
                raw.get("fail_open_when_unknown", cls.fail_open_when_unknown)
            ),
        )


def _coerce_unix_seconds(value: Any) -> float | None:
    """Best-effort conversion of a Raydium time field to unix seconds."""

    if value in (None, "", 0, "0"):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    if seconds > 1e12:
        seconds /= 1000.0
    return seconds


def extract_pool_open_time(raw: Any) -> float | None:
    """Pull a unix-seconds creation timestamp out of a raw Raydium pool dict."""

    if not isinstance(raw, dict):
        return None
    for key in ("openTime", "open_time", "createTime", "createdAt", "createdTime"):
        seconds = _coerce_unix_seconds(raw.get(key))
        if seconds is not None:
            return seconds
    for window_key in ("day", "week", "month"):
        window = raw.get(window_key)
        if isinstance(window, dict):
            for key in ("startTime", "start_time", "start"):
                seconds = _coerce_unix_seconds(window.get(key))
                if seconds is not None:
                    return seconds
    return None


def pool_age_seconds(pool: dict[str, Any], now: datetime | None = None) -> float | None:
    """Return the pool age in seconds, or None when not determinable."""

    raw = pool.get("raw")
    open_seconds = extract_pool_open_time(raw)
    if open_seconds is None:
        return None
    current = (now or datetime.now(UTC)).timestamp()
    return max(0.0, current - open_seconds)


def evaluate_pool_age_guard(
    pool: dict[str, Any],
    config: PoolAgeGuardConfig,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails)."""

    if not config.enabled:
        return True, None

    age = pool_age_seconds(pool, now=now)
    if age is None:
        if config.fail_open_when_unknown:
            return True, None
        return False, "pool creation time unknown; pool_age_guard rejects unknown-age pools"

    age_minutes = age / 60.0
    if age_minutes < config.min_age_minutes:
        return False, (
            f"pool age {age_minutes:.1f} min below min {config.min_age_minutes:.1f} min "
            f"(too fresh to trust the APR signal)"
        )

    if config.max_age_days > 0:
        age_days = age / 86_400.0
        if age_days > config.max_age_days:
            return False, (
                f"pool age {age_days:.2f} days above max {config.max_age_days:.2f} days "
                f"(fee APR is probably already arbed down)"
            )

    return True, None
