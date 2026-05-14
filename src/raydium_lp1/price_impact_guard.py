"""PriceImpactGuard: refuse pools where our future entry would crater the price.

The name to remember is **price_impact_guard**.

What it asks, in plain English:
- If we (later) deposit `max_position_usd` worth of the quote asset and the
  AMM has to absorb it, how much will the spot price move? In a constant-
  product (`x*y=k`) AMM the price impact for an additive trade of size `dx`
  against a reserve of size `x` is approximately `dx / (x + dx)` (relative).
  For a $25 entry into a pool with $5M TVL ($2.5M per side), price impact is
  around 0.001% — fine. For a $25 entry into a pool with $50 TVL it is ~50%
  — catastrophic.
- This guard estimates impact from TVL alone. We approximate "quote-side
  reserve" as half the TVL (the usual 50/50 starting state). Concentrated
  pools concentrate liquidity, so for CLMM pools we use the same ratio
  unless the pool snapshot provides better info.

Output is a percentage. Pool is rejected when impact > `max_impact_percent`.

This filter is **pure**: it only uses the Raydium snapshot and config. It
never calls any RPC. Settings live under `price_impact_guard` in
`config/settings.json`. See SETTINGS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PriceImpactGuardConfig:
    enabled: bool = True
    max_impact_percent: float = 1.0
    quote_side_fraction: float = 0.5

    @classmethod
    def from_raw(cls, raw: Any) -> "PriceImpactGuardConfig":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            max_impact_percent=float(raw.get("max_impact_percent", cls.max_impact_percent)),
            quote_side_fraction=float(raw.get("quote_side_fraction", cls.quote_side_fraction)),
        )


def estimate_price_impact_pct(
    pool: dict[str, Any],
    max_position_usd: float,
    quote_side_fraction: float = 0.5,
) -> float:
    """Constant-product estimate: dx / (x + dx) expressed in percent."""

    tvl = float(pool.get("liquidity_usd") or 0.0)
    if tvl <= 0 or max_position_usd <= 0:
        return 100.0
    quote_reserve = max(tvl * max(0.0, min(1.0, quote_side_fraction)), 1e-9)
    impact = max_position_usd / (quote_reserve + max_position_usd)
    return impact * 100.0


def evaluate_price_impact_guard(
    pool: dict[str, Any],
    config: PriceImpactGuardConfig,
    max_position_usd: float,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails)."""

    if not config.enabled:
        return True, None

    impact = estimate_price_impact_pct(
        pool,
        max_position_usd=max_position_usd,
        quote_side_fraction=config.quote_side_fraction,
    )
    if impact > config.max_impact_percent:
        return False, (
            f"estimated price impact {impact:.3f}% on a ${max_position_usd:.2f} entry "
            f"exceeds max {config.max_impact_percent:.3f}% (pool too small for this position)"
        )
    return True, None


__all__ = [
    "PriceImpactGuardConfig",
    "estimate_price_impact_pct",
    "evaluate_price_impact_guard",
]
