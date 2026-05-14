"""FeeAprFloor: require a minimum *fee-derived* APR, not just reward-token APR.

The name to remember is **fee_apr_floor**.

Why this matters, in plain English:
- The headline APR Raydium shows often combines (a) the real trading fees
  earned by LPs, with (b) emissions of farm-reward tokens that the team
  pays out for a short marketing window. Once those rewards stop, the APR
  collapses to whatever the fees alone produce.
- The fee-only APR is roughly `24h_fees_usd * 365 / tvl_usd * 100%`. If that
  number is below the configured floor, the pool's economics depend on
  rewards that are about to end. We reject those.

The scanner already extracts `fee_24h_usd` and `liquidity_usd`, so this
filter is **pure**: no RPC, no extra API call. Settings live under
`fee_apr_floor` in `config/settings.json`. See SETTINGS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeeAprFloorConfig:
    enabled: bool = True
    min_fee_apr_percent: float = 30.0

    @classmethod
    def from_raw(cls, raw: Any) -> "FeeAprFloorConfig":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            min_fee_apr_percent=float(
                raw.get("min_fee_apr_percent", cls.min_fee_apr_percent)
            ),
        )


def estimate_fee_apr_percent(pool: dict[str, Any]) -> float:
    """Annualized fee APR as a percent. Returns 0 when TVL is unknown."""

    tvl = float(pool.get("liquidity_usd") or 0.0)
    fees_24h = float(pool.get("fee_24h_usd") or 0.0)
    if tvl <= 0:
        return 0.0
    return (fees_24h / tvl) * 365.0 * 100.0


def evaluate_fee_apr_floor(
    pool: dict[str, Any],
    config: FeeAprFloorConfig,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails)."""

    if not config.enabled:
        return True, None
    fee_apr = estimate_fee_apr_percent(pool)
    if fee_apr < config.min_fee_apr_percent:
        return False, (
            f"fee-only APR {fee_apr:.2f}% below floor {config.min_fee_apr_percent:.2f}% "
            f"(headline APR depends on farm rewards that can end at any time)"
        )
    return True, None


__all__ = [
    "FeeAprFloorConfig",
    "estimate_fee_apr_percent",
    "evaluate_fee_apr_floor",
]
