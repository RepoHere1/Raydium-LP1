"""Raydium «Create pool» feasibility — honest limits for fee-certainty claims."""

from __future__ import annotations

from typing import Any


def analyze_create_pool_feasibility() -> dict[str, Any]:
    """Structured analysis for dashboard + CLI (not financial advice)."""

    return {
        "title": "Can you «brainiac create» a Raydium pool with near-certain fees?",
        "verdict_short": (
            "No honest certainty — you can bias odds with pair, fee tier, and marketing, "
            "but you cannot guarantee volume or that LPs stay in-range."
        ),
        "sections": [
            {
                "heading": "What «Create pool» actually does",
                "body": (
                    "You deploy a new CLMM pool (two mints, fee tier, initial price/tick). "
                    "Until traders swap through it, fee_24h stays near zero. Your LP only earns "
                    "when swaps cross ticks where your liquidity is active."
                ),
            },
            {
                "heading": "Why fee $ cannot be guaranteed",
                "body": (
                    "Fees = (swap volume) × (pool fee rate) × (your share of active liquidity). "
                    "Volume is exogenous (meme cycle, listings, bots). Competitors can open the "
                    "same pair at a lower fee tier. A created pool can sit idle indefinitely."
                ),
            },
            {
                "heading": "When creation beats joining an existing pool",
                "body": (
                    "Creation only makes sense if you control distribution: you are the main "
                    "token project, you will route your own treasury swaps, or you capture a "
                    "first-mover pair before duplicates appear. Otherwise joining a pool with "
                    "proven fee_24h and routes (this experiment) is strictly more measurable."
                ),
            },
            {
                "heading": "Highest-probability create-pool playbook (still risky)",
                "body": (
                    "SOL/USDC or SOL/major: saturated — hard to steal flow. "
                    "New meme + SOL/USDC quote: possible fee spikes if you drive volume, but "
                    "rug/pull risk and duplicate pools. "
                    "1–4% fee tier: higher $/swap when volume exists; 0.01% tier needs huge volume. "
                    "You still need: deep routes both ways, $5k+ seed TVL, and tight band near spot."
                ),
            },
            {
                "heading": "How SUPER-BRAINIAC uses this",
                "body": (
                    "This experiment scans existing Raydium CLMM pools only — it scores where "
                    "your $3 clip is likely to sit in-range and capture a measurable slice of "
                    "observed 24h fees. Create-pool is documented here for comparison, not auto-run."
                ),
            },
        ],
        "metrics_to_watch_if_you_create": [
            "fee_24h_usd after 24h (not APR headline)",
            "volume_24h / TVL (churn)",
            "duplicate pools same pair lower fee tier",
            "Jupiter buy+sell routes for both mints",
            "your in-range time % (on-chain ticks vs spot)",
        ],
    }
