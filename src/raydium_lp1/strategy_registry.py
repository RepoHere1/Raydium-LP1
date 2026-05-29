"""
strategy_registry v1.0 — official names + definitions for the 6 LP strategies.

This is the canonical list of named LP strategies the bot can deploy on
Raydium CLMM. Each strategy specifies:

  - name        : industry-standard term
  - definition  : one-line plain-English description
  - knobs       : settings the user can tune via the settings UI
  - inputs      : live data sources the strategy reads (live_data API names)
  - mode        : "always_on" | "demo_safe" | "live_only"
  - notes       : caveats, fee implications, capital requirements

User picked these 6 from a longer list — Reactive Rebalancing was excluded
per a previous bad experience on Krystal DeFi.

Used by:
  - strategy_picker.html UI (lists strategies with descriptions)
  - bot_core (loads selected strategy + applies knobs)
  - settings_io (validates strategy names against this registry)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---- the registry -------------------------------------------------------

STRATEGIES: list[dict] = [
    {
        "id":         "range_order",
        "name":       "Range Order",
        "tagline":    "Single-sided band acts as a limit order with fee yield.",
        "definition": (
            "Single-sided LP placed entirely above (or below) current spot, "
            "acting as a price-improvement limit order. As price crosses your "
            "band, your held token gets converted to the opposite side at "
            "progressively better prices than a market sell would give. "
            "Uniswap V3 invented the term."
        ),
        "knobs": {
            "side":              {"type": "enum",  "values": ["above", "below"], "default": "above"},
            "start_pct":         {"type": "float", "default": 1.0,  "min": 0.1,  "max": 50.0,
                                  "desc": "band starts this % away from spot"},
            "width_pct":         {"type": "float", "default": 5.0,  "min": 0.5,  "max": 100.0,
                                  "desc": "band is this wide"},
        },
        "inputs":     [],
        "mode":       "always_on",
        "notes":      "Best for single-direction trading bias (e.g. exit on rallies).",
    },
    {
        "id":         "dynamic_range_width",
        "name":       "Volatility-Adaptive Bands (DRW)",
        "tagline":    "Width = k × σ × √t — scales with realized vol.",
        "definition": (
            "Band width is set proportional to recent realized volatility. "
            "Standard formula: width = k × σ × √t where σ is implied or 24h "
            "realized vol, t is hold time in days, k is a risk knob (typical "
            "1.0-2.5). Wider bands when chop is high, tighter when calm. "
            "Used by Kamino Vaults, Charm Alpha Vaults, Arrakis PALM."
        ),
        "knobs": {
            "k_factor":          {"type": "float", "default": 1.5, "min": 0.5, "max": 3.0,
                                  "desc": "risk multiplier (higher = wider band)"},
            "hold_days":         {"type": "float", "default": 1.0, "min": 0.1, "max": 30.0,
                                  "desc": "expected position lifetime in days"},
            "vol_lookback_hours":{"type": "int",   "default": 24,  "min": 1,   "max": 168,
                                  "desc": "realized-vol window"},
        },
        "inputs":     ["realized_vol_24h"],
        "mode":       "always_on",
        "notes":      "Needs vol data feed. Falls back to fixed 5% if vol unavailable.",
    },
    {
        "id":         "momentum_anchored",
        "name":       "Trailing-Edge / Momentum-Anchored LP",
        "tagline":    "Asymmetric offset based on short-term momentum.",
        "definition": (
            "Places the band 1-3% above spot on clear uptrends (so you can "
            "'sell into rallies' mechanically), snug to spot during chop, "
            "below spot during downtrends. Sometimes called Momentum-Anchored "
            "LP. Reads 1h price slope or 14-period RSI."
        ),
        "knobs": {
            "uptrend_offset_pct":  {"type": "float", "default": 2.0, "min": 0.0, "max": 10.0},
            "chop_offset_pct":     {"type": "float", "default": 0.5, "min": 0.0, "max": 5.0},
            "rsi_uptrend_thresh":  {"type": "int",   "default": 60,  "min": 50,  "max": 80},
            "rsi_downtrend_thresh":{"type": "int",   "default": 40,  "min": 20,  "max": 50},
        },
        "inputs":     ["price_slope_1h", "rsi_14"],
        "mode":       "always_on",
        "notes":      "Strong on trending markets, mediocre in mean-reverting chop.",
    },
    {
        "id":         "fee_tier_arbitrage",
        "name":       "Fee Tier Arbitrage (FTS)",
        "tagline":    "Pick the pool/tier where (volume × fee) / TVL is highest.",
        "definition": (
            "Raydium CLMM has multiple fee tiers per pair (0.01%, 0.05%, "
            "0.25%, 1.00%). Scan all tiers and pick where 24h_volume × "
            "fee_pct / TVL is highest. For SOL/USDC this almost always "
            "means 0.05%. For volatile memecoins it's 1%. Migrates "
            "liquidity when another tier becomes more profitable."
        ),
        "knobs": {
            "min_apr_pct":       {"type": "float", "default": 5.0,  "min": 0.0,  "max": 1000.0},
            "rebalance_threshold_pct": {"type": "float", "default": 20.0, "min": 5.0, "max": 100.0,
                                       "desc": "% APR improvement needed to migrate"},
            "fee_tiers_allowed": {"type": "csv_floats", "default": "0.0001,0.0005,0.0025,0.01"},
        },
        "inputs":     ["raydium_pools_api"],
        "mode":       "always_on",
        "notes":      "Migration costs gas — don't set rebalance_threshold too low.",
    },
    {
        "id":         "bin_density_cvp",
        "name":       "Bin-Density / Concentrated Volume Profile (CVP)",
        "tagline":    "Place narrow bands at historical volume nodes.",
        "definition": (
            "Uses on-chain swap data to find price levels with densest "
            "historical volume, then places narrow concentrated positions "
            "right at those volume nodes. Mimics what Meteora DLMM vaults "
            "do automatically. Volume nodes act as natural support/resistance."
        ),
        "knobs": {
            "lookback_hours":    {"type": "int",   "default": 168, "min": 24,  "max": 720,
                                  "desc": "swap-history window"},
            "top_n_nodes":       {"type": "int",   "default": 3,   "min": 1,   "max": 10,
                                  "desc": "how many volume nodes to anchor on"},
            "band_width_pct":    {"type": "float", "default": 0.5, "min": 0.1, "max": 5.0,
                                  "desc": "tight band around each node"},
        },
        "inputs":     ["raydium_swap_history", "price_history"],
        "mode":       "always_on",
        "notes":      "Best with at least 7 days of swap history. New pools have noisy nodes.",
    },
    {
        "id":         "jit_lp",
        "name":       "Just-In-Time (JIT) LP",
        "tagline":    "Single-block position around a known large incoming swap.",
        "definition": (
            "Opens a concentrated single-block position right before a known "
            "large incoming swap (e.g. MEV-visible Jupiter route), captures "
            "the fee on that swap, closes the position the next block. "
            "Requires Jito bundle access (~0.001 SOL tip per attempt) and "
            "reliable Helius/Triton WebSocket. Adversarial to retail; "
            "you'd be running JIT, not against it."
        ),
        "knobs": {
            "min_swap_size_usd": {"type": "float", "default": 5000, "min": 100, "max": 1000000,
                                  "desc": "only target swaps above this size"},
            "jito_tip_sol":      {"type": "float", "default": 0.001, "min": 0.0001, "max": 0.1},
            "max_position_pct":  {"type": "float", "default": 50.0, "min": 1.0, "max": 100.0,
                                  "desc": "% of bankroll to risk per JIT attempt"},
        },
        "inputs":     ["jito_mempool_ws", "jupiter_route_bundles"],
        "mode":       "live_only",
        "notes":      "ADVANCED — extra setup required. Tips eat into PnL on failed attempts.",
    },
]

# ---- public API ---------------------------------------------------------

def all_strategies() -> list[dict]:
    return STRATEGIES


def get(strategy_id: str) -> dict | None:
    for s in STRATEGIES:
        if s["id"] == strategy_id:
            return s
    return None


def validate_settings(strategy_id: str, settings: dict) -> dict:
    """Returns {ok, normalized_settings, errors[]}.
       Coerces types, clamps to min/max, fills defaults for missing knobs."""
    s = get(strategy_id)
    if not s:
        return {"ok": False, "errors": [f"unknown strategy_id: {strategy_id}"]}

    out: dict = {}
    errors: list[str] = []
    for knob_name, spec in s["knobs"].items():
        raw = settings.get(knob_name, spec.get("default"))
        try:
            if spec["type"] == "float":
                v = float(raw)
                if "min" in spec: v = max(spec["min"], v)
                if "max" in spec: v = min(spec["max"], v)
                out[knob_name] = v
            elif spec["type"] == "int":
                v = int(raw)
                if "min" in spec: v = max(spec["min"], v)
                if "max" in spec: v = min(spec["max"], v)
                out[knob_name] = v
            elif spec["type"] == "enum":
                v = str(raw)
                if v not in spec["values"]:
                    errors.append(f"{knob_name}={v!r} not in {spec['values']}")
                    v = spec["default"]
                out[knob_name] = v
            elif spec["type"] == "csv_floats":
                if isinstance(raw, str):
                    out[knob_name] = [float(x.strip()) for x in raw.split(",") if x.strip()]
                elif isinstance(raw, list):
                    out[knob_name] = [float(x) for x in raw]
                else:
                    out[knob_name] = [float(x) for x in str(raw).split(",")]
            else:
                out[knob_name] = raw
        except (ValueError, TypeError) as e:
            errors.append(f"{knob_name} coercion failed: {e}")
            out[knob_name] = spec.get("default")

    return {"ok": len(errors) == 0, "errors": errors, "normalized_settings": out,
            "strategy": {"id": s["id"], "name": s["name"]}}


def to_ui_json() -> str:
    """Serializable form for the settings UI (drops Python-only fields)."""
    return json.dumps([
        {k: v for k, v in s.items()}
        for s in STRATEGIES
    ], indent=2)


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for s in STRATEGIES:
            mode_tag = f"[{s['mode']}]".ljust(13)
            print(f"  {mode_tag} {s['name']}")
            print(f"                {s['tagline']}")
            print()
    elif cmd == "json":
        print(to_ui_json())
    elif cmd == "validate" and len(sys.argv) > 2:
        strategy_id = sys.argv[2]
        settings = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(validate_settings(strategy_id, settings), indent=2))
    elif cmd == "get" and len(sys.argv) > 2:
        s = get(sys.argv[2])
        print(json.dumps(s, indent=2) if s else "(not found)")
    else:
        print("usage: strategy_registry.py [list|json|get <id>|validate <id> [settings_json]]")
        sys.exit(2)
