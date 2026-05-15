"""Filter strategy presets for Raydium-LP1.

Presets let the user pick a risk appetite without hand-tuning every threshold.
Values cover ``min_apr`` (percent), ``min_liquidity_usd`` and
``min_volume_24h_usd``. The scanner reads these via :func:`apply_strategy` and
merges them into a :class:`raydium_lp1.scanner.ScannerConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

STRATEGY_CONSERVATIVE = "conservative"
STRATEGY_MODERATE = "moderate"
STRATEGY_AGGRESSIVE = "aggressive"
STRATEGY_DEGEN = "degen"
STRATEGY_MOMENTUM = "momentum"
STRATEGY_CUSTOM = "custom"

ALLOWED_STRATEGIES = (
    STRATEGY_CONSERVATIVE,
    STRATEGY_MODERATE,
    STRATEGY_AGGRESSIVE,
    STRATEGY_DEGEN,
    STRATEGY_MOMENTUM,
    STRATEGY_CUSTOM,
)

# Extra settings applied when strategy=momentum (fee-rush / short-hold LP hunting).
MOMENTUM_STRATEGY_EXTRAS: dict[str, object] = {
    "momentum_enabled": True,
    "min_momentum_score": 55.0,
    "require_momentum_score": False,
    "momentum_hold_hours": 24.0,
    "momentum_min_volume_tvl_ratio": 0.5,
    "momentum_sweet_min_pool_age_hours": 6.0,
    "momentum_sweet_max_pool_age_hours": 168.0,
    "momentum_min_tvl_usd": 5000.0,
    "min_liquidity_usd": 5000.0,
    "hard_exit_min_tvl_usd": 1000.0,
    "momentum_top_hot": 25,
    "momentum_detective_enabled": True,
    "momentum_probe_market_lists": True,
    "sort_candidates_by_momentum": True,
    "max_pool_age_hours": 168.0,
    "min_pool_age_hours": 6.0,
    "pages": 3,
}


@dataclass(frozen=True)
class StrategyPreset:
    name: str
    min_apr: float
    min_liquidity_usd: float
    min_volume_24h_usd: float
    description: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "min_apr": self.min_apr,
            "min_liquidity_usd": self.min_liquidity_usd,
            "min_volume_24h_usd": self.min_volume_24h_usd,
            "description": self.description,
        }


STRATEGY_PRESETS: dict[str, StrategyPreset] = {
    STRATEGY_CONSERVATIVE: StrategyPreset(
        name=STRATEGY_CONSERVATIVE,
        min_apr=50.0,
        min_liquidity_usd=50_000.0,
        min_volume_24h_usd=10_000.0,
        description="Established pairs only. Boring on purpose.",
    ),
    STRATEGY_MODERATE: StrategyPreset(
        name=STRATEGY_MODERATE,
        min_apr=200.0,
        min_liquidity_usd=10_000.0,
        min_volume_24h_usd=1_000.0,
        description="Mid-cap yield with reasonable liquidity floor.",
    ),
    STRATEGY_AGGRESSIVE: StrategyPreset(
        name=STRATEGY_AGGRESSIVE,
        min_apr=777.0,
        min_liquidity_usd=500.0,
        min_volume_24h_usd=100.0,
        description="High-APR hunting; tolerates thinner pools.",
    ),
    STRATEGY_DEGEN: StrategyPreset(
        name=STRATEGY_DEGEN,
        min_apr=500.0,
        min_liquidity_usd=200.0,
        min_volume_24h_usd=50.0,
        description="Anything that pumps. Plan your exit before entering.",
    ),
    STRATEGY_MOMENTUM: StrategyPreset(
        name=STRATEGY_MOMENTUM,
        min_apr=300.0,
        min_liquidity_usd=5_000.0,
        min_volume_24h_usd=500.0,
        description=(
            "Real TVL + buyer flow: rank pools by live vol/TVL, acceleration, APR; "
            "exit hints when health/TVL/volume fail."
        ),
    ),
}


def get_preset(name: str) -> StrategyPreset | None:
    """Return the named preset (case-insensitive) or ``None`` for custom."""

    key = (name or "").strip().lower()
    if key in (STRATEGY_CUSTOM, ""):
        return None
    return STRATEGY_PRESETS.get(key)


def normalize_strategy(name: str | None) -> str:
    if not name:
        return STRATEGY_CUSTOM
    key = name.strip().lower()
    if key in ("fee_rush", "hot_lp", "fee-rush"):
        return STRATEGY_MOMENTUM
    if key in ALLOWED_STRATEGIES:
        return key
    return STRATEGY_CUSTOM


def apply_strategy(raw_config: Mapping[str, object], strategy: str | None) -> dict[str, object]:
    """Return a new config dict with preset filter values applied.

    Explicit values already present in ``raw_config`` win over preset defaults
    so users can still override individual thresholds without leaving the
    preset. Pass ``strategy="custom"`` (or ``None``) to leave the config
    untouched.
    """

    merged: dict[str, object] = dict(raw_config)
    normalized = normalize_strategy(strategy)
    merged["strategy"] = normalized
    preset = get_preset(normalized)
    if preset is None:
        return merged

    for key, value in (
        ("min_apr", preset.min_apr),
        ("min_liquidity_usd", preset.min_liquidity_usd),
        ("min_volume_24h_usd", preset.min_volume_24h_usd),
    ):
        if key not in raw_config:
            merged[key] = value
    if normalized == STRATEGY_MOMENTUM:
        for key, value in MOMENTUM_STRATEGY_EXTRAS.items():
            if key not in raw_config:
                merged[key] = value
    return merged


def describe_presets() -> str:
    """Human-friendly multi-line description used by the setup wizard."""

    lines = ["Available strategies:"]
    for key in (
        STRATEGY_CONSERVATIVE,
        STRATEGY_MODERATE,
        STRATEGY_AGGRESSIVE,
        STRATEGY_DEGEN,
        STRATEGY_MOMENTUM,
    ):
        preset = STRATEGY_PRESETS[key]
        lines.append(
            f"  - {preset.name:<13} APR>={preset.min_apr:>6.0f}%  "
            f"TVL>=${preset.min_liquidity_usd:>8.0f}  "
            f"Vol24h>=${preset.min_volume_24h_usd:>6.0f}  -- {preset.description}"
        )
    lines.append("  - custom        Use whatever values you set manually in settings.json")
    return "\n".join(lines)
