"""Skew-range LP placement optimizer — find the hottest band relative to spot.

The deep fee gold mine in concentrated LPs is TIME-IN-RANGE, not raw APR. Two
forces pull against each other:

  * Concentration: a TIGHT band puts more of your liquidity at the active tick,
    so you earn a larger share of swap fees PER DOLLAR — but only while price is
    inside the band.
  * Survival: a WIDE band stays in range through volatility, so it keeps earning
    (and avoids being knocked fully into one asset at the worst price).

For volatile tokens ("they go all over the place, I'm out of range quick") the
expected-value optimum sits WIDE, because being out of range = 0 fees + adverse
inventory. This module quantifies that and emits a recommended band with an
explicit wide bias.

Method (all from live data the scanner already has):
  1. realized volatility from the day price range (priceMin/priceMax) → daily sigma.
  2. drift/skew from momentum + detective inflow bias → shift band center.
  3. for each candidate width, estimate P(stay in range over the holding horizon)
     using a normal random-walk model, and a fee-capture score
     ~ concentration(width) * in_range_prob(width).
  4. pick the width maximizing score, then apply a configurable WIDE BIAS that
     deliberately steps toward wider bands (favoring survival for runner tokens).

Pure stdlib + math. Paper-plan output (no signing); plugs into lp_range_planner
and the orchestrator. Reuses momentum_skew() from lp_range_planner.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from raydium_lp1.lp_range_planner import momentum_skew, spot_price_quote_per_base

# range of a normal sample over a window ≈ ~4σ (mean range of N(0,1) draws),
# so daily sigma ≈ observed_swing_fraction / RANGE_TO_SIGMA.
RANGE_TO_SIGMA = 4.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def daily_sigma_fraction(pool: Mapping[str, Any]) -> tuple[float, str]:
    """Estimate 1-day volatility as a fraction of spot (0.10 = ±10%/day-ish)."""
    raw = pool.get("raw") if isinstance(pool.get("raw"), dict) else {}
    day = raw.get("day") if isinstance(raw.get("day"), dict) else {}
    pmin = float(day.get("priceMin") or 0)
    pmax = float(day.get("priceMax") or 0)
    if pmin > 0 and pmax > pmin:
        mid = (pmin + pmax) / 2.0
        swing = (pmax - pmin) / mid
        return swing / RANGE_TO_SIGMA, f"day_range swing={swing*100:.1f}%"
    # Fallback: infer from churn (vol/TVL). Busier pools tend to be more volatile.
    vol = float(pool.get("volume_24h_usd") or 0)
    tvl = float(pool.get("liquidity_usd") or pool.get("tvl_usd") or 0)
    churn = (vol / tvl) if tvl > 0 else 0.0
    # crude map: churn 0->~5%/day, 2->~20%, 5+->~40%
    sigma = _clamp(0.05 + 0.07 * churn, 0.05, 0.60)
    return sigma, f"churn_fallback churn={churn:.2f}"


def in_range_prob(half_width_frac: float, sigma_h: float) -> float:
    """P(|price move| < half_width) over the horizon, normal random walk.

    half_width_frac: half the band width as a fraction of spot (e.g. 0.25 = ±25%).
    sigma_h: horizon volatility as a fraction of spot.
    """
    if sigma_h <= 0:
        return 1.0
    z = half_width_frac / sigma_h
    # P(|Z| < z) = erf(z / sqrt(2))
    return math.erf(z / math.sqrt(2.0))


def fee_score(width_frac: float, in_prob: float, penalty_exp: float = 2.0) -> float:
    """Relative expected fee capture with an out-of-range penalty.

    Concentration ~ 1/width rewards tight bands, but being out of range costs you
    twice: zero fees AND a forced rebalance (gas + adverse inventory). We model that
    by raising in_range_prob to penalty_exp (>1), which makes the score collapse as
    the band gets too tight to survive. penalty_exp=1 -> no penalty (optimum at the
    tightest band); 2-3 -> realistic, yields an INTERIOR optimum that widens with
    volatility. Returns 0 at the degenerate edges."""
    if width_frac <= 0:
        return 0.0
    concentration = 1.0 / width_frac
    return concentration * (in_prob ** max(1.0, penalty_exp))


@dataclass(frozen=True)
class SkewPlan:
    spot: float | None
    spot_source: str
    sigma_daily_frac: float
    sigma_source: str
    horizon_days: float
    sigma_horizon_frac: float
    skew: float
    skew_notes: list[str]
    chosen_width_pct: float
    ev_optimal_width_pct: float
    wide_bias_applied: bool
    in_range_prob: float
    fee_score: float
    lower_mult: float          # band lower / spot
    upper_mult: float          # band upper / spot
    lower_quote: float | None
    upper_quote: float | None
    candidates_scored: list[dict] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "spot": self.spot,
            "spot_source": self.spot_source,
            "sigma_daily_frac": round(self.sigma_daily_frac, 4),
            "sigma_source": self.sigma_source,
            "horizon_days": self.horizon_days,
            "sigma_horizon_frac": round(self.sigma_horizon_frac, 4),
            "skew": round(self.skew, 3),
            "skew_notes": self.skew_notes,
            "chosen_width_pct": round(self.chosen_width_pct, 2),
            "ev_optimal_width_pct": round(self.ev_optimal_width_pct, 2),
            "wide_bias_applied": self.wide_bias_applied,
            "in_range_prob": round(self.in_range_prob, 3),
            "fee_score": round(self.fee_score, 3),
            "band_vs_spot": {"lower_mult": round(self.lower_mult, 4),
                             "upper_mult": round(self.upper_mult, 4)},
            "lower_quote_per_base": self.lower_quote,
            "upper_quote_per_base": self.upper_quote,
            "candidates_scored": self.candidates_scored,
            "rationale": self.rationale,
        }


def optimize_band(
    pool: Mapping[str, Any],
    momentum: Mapping[str, Any] | None = None,
    *,
    width_candidates: tuple[float, ...] = (10, 15, 20, 30, 40, 50, 65, 80),
    horizon_days: float = 1.0,
    wide_bias: float = 0.35,
    min_in_range_prob: float = 0.0,
    out_of_range_penalty: float = 2.0,
    use_momentum: bool = True,
) -> SkewPlan:
    """Compute the recommended skewed band for one pool.

    wide_bias in [0,1]: 0 = pick pure EV-optimal width; 1 = always pick the widest
    candidate that still clears min_in_range_prob. The default 0.35 leans wide,
    matching runner-token behaviour where out-of-range is costly.
    """
    spot, spot_src = spot_price_quote_per_base(pool)
    sigma_d, sigma_src = daily_sigma_fraction(pool)
    sigma_h = sigma_d * math.sqrt(max(0.01, horizon_days))
    skew, skew_notes = momentum_skew(momentum, use_momentum=use_momentum)

    cands = sorted({float(w) for w in width_candidates if float(w) > 0})
    scored: list[dict] = []
    for w in cands:
        half = (w / 100.0) / 2.0
        p = in_range_prob(half, sigma_h)
        s = fee_score(w / 100.0, p, out_of_range_penalty)
        scored.append({"width_pct": w, "in_range_prob": round(p, 3),
                       "fee_score": round(s, 3)})

    # EV-optimal = highest fee_score among candidates meeting the prob floor.
    eligible = [c for c in scored if c["in_range_prob"] >= min_in_range_prob] or scored
    ev_best = max(eligible, key=lambda c: c["fee_score"])
    ev_width = ev_best["width_pct"]

    # Apply wide bias: interpolate index from EV-optimal toward the widest eligible.
    widths = [c["width_pct"] for c in eligible]
    ev_idx = widths.index(ev_width)
    max_idx = len(widths) - 1
    chosen_idx = round(ev_idx + wide_bias * (max_idx - ev_idx))
    chosen_idx = int(_clamp(chosen_idx, 0, max_idx))
    chosen_width = widths[chosen_idx]
    wide_applied = chosen_width > ev_width
    chosen = next(c for c in eligible if c["width_pct"] == chosen_width)

    # Asymmetric placement: skew>0 puts more room ABOVE spot (expecting up-move).
    w = chosen_width / 100.0
    sk = _clamp(skew, -1.0, 1.0)
    down_share = 0.5 - 0.25 * sk
    lower_mult = 1.0 - w * down_share
    upper_mult = 1.0 + w * (1.0 - down_share)
    lower_q = round(spot * lower_mult, 10) if spot else None
    upper_q = round(spot * upper_mult, 10) if spot else None

    rationale = (
        f"sigma_daily≈{sigma_d*100:.1f}% ({sigma_src}); horizon {horizon_days}d → "
        f"sigma_h≈{sigma_h*100:.1f}%. EV-optimal width={ev_width}% "
        f"(in-range {ev_best['in_range_prob']:.0%}, score {ev_best['fee_score']:.2f}). "
        f"Wide bias {wide_bias:.0%} → chose {chosen_width}% "
        f"(in-range {chosen['in_range_prob']:.0%}). "
        f"Skew {sk:+.2f} → {'more room above' if sk>0 else 'more room below' if sk<0 else 'symmetric'} spot."
    )

    return SkewPlan(
        spot=spot, spot_source=spot_src,
        sigma_daily_frac=sigma_d, sigma_source=sigma_src,
        horizon_days=horizon_days, sigma_horizon_frac=sigma_h,
        skew=sk, skew_notes=skew_notes,
        chosen_width_pct=chosen_width, ev_optimal_width_pct=ev_width,
        wide_bias_applied=wide_applied,
        in_range_prob=chosen["in_range_prob"], fee_score=chosen["fee_score"],
        lower_mult=lower_mult, upper_mult=upper_mult,
        lower_quote=lower_q, upper_quote=upper_q,
        candidates_scored=scored, rationale=rationale,
    )


if __name__ == "__main__":
    import json
    # Demo: a volatile runner with a wide daily range.
    demo = {
        "id": "demo", "mint_a_symbol": "RUNNER", "mint_b_symbol": "USDC",
        "volume_24h_usd": 2_000_000, "liquidity_usd": 400_000,
        "raw": {"day": {"priceMin": 0.80, "priceMax": 1.40}},
    }
    mom = {"detective": {"inflow_bias": 30, "sniff_tags": ["volume_surging_vs_7d"]}}
    plan = optimize_band(demo, mom, horizon_days=1.0, wide_bias=0.35)
    print(json.dumps(plan.to_dict(), indent=2))
