"""
filter_suite v1.0 — composable filter chain for Raydium LP candidates.

Ported from FutureGMGN's filter_suite.py, adapted for Raydium-LP1's
domain (LP pools instead of prediction-market trades). Filters are pure
functions: input = candidate dict, output = {pass: bool, reason: str}.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent.parent
REJECT_LOG_PATH = REPO / "rejects.json"

FilterFn = Callable[[dict, dict], dict]   # (cand, cfg) -> {pass, reason}


def filter_min_tvl(cand: dict, cfg: dict) -> dict:
    """Reject pools with TVL below threshold (avoids slippage spirals)."""
    min_tvl = float(cfg.get("min_pool_tvl_usd", 100_000))
    tvl = float(cand.get("tvl_usd", 0))
    if tvl < min_tvl:
        return {"pass": False, "reason": f"tvl ${tvl:,.0f} < min ${min_tvl:,.0f}"}
    return {"pass": True, "reason": "tvl ok"}


def filter_min_apr(cand: dict, cfg: dict) -> dict:
    """Reject pools below minimum APR (not worth gas cost)."""
    min_apr = float(cfg.get("min_apr_pct", 5.0))
    apr = float(cand.get("apr_pct", 0))
    if apr < min_apr:
        return {"pass": False, "reason": f"apr {apr:.2f}% < min {min_apr}%"}
    return {"pass": True, "reason": "apr ok"}


def filter_max_spread(cand: dict, cfg: dict) -> dict:
    """Reject pools where current bid/ask spread is wider than threshold."""
    max_bps = float(cfg.get("max_spread_bps", 50))
    spread = float(cand.get("spread_bps", 0))
    if spread > max_bps:
        return {"pass": False, "reason": f"spread {spread:.1f}bps > max {max_bps}bps"}
    return {"pass": True, "reason": "spread ok"}


def filter_pool_age(cand: dict, cfg: dict) -> dict:
    """Reject pools younger than min_age_days. Brand-new pools are rug-prone."""
    min_age = int(cfg.get("min_pool_age_days", 1))
    age = int(cand.get("age_days", 0))
    if age < min_age:
        return {"pass": False, "reason": f"pool age {age}d < min {min_age}d"}
    return {"pass": True, "reason": "age ok"}


def filter_token_allowlist(cand: dict, cfg: dict) -> dict:
    """If allowlist is non-empty, both mints must be in it."""
    allow = set(cfg.get("token_allowlist", []) or [])
    if not allow:
        return {"pass": True, "reason": "no allowlist"}
    a = cand.get("mint_a_symbol", "")
    b = cand.get("mint_b_symbol", "")
    if a not in allow:
        return {"pass": False, "reason": f"mint_a {a!r} not in allowlist"}
    if b not in allow:
        return {"pass": False, "reason": f"mint_b {b!r} not in allowlist"}
    return {"pass": True, "reason": "tokens allowed"}


def filter_token_denylist(cand: dict, cfg: dict) -> dict:
    """Reject pools where either mint is on the denylist (scam tokens, etc.)."""
    deny = set(cfg.get("token_denylist", []) or [])
    if not deny:
        return {"pass": True, "reason": "no denylist"}
    a = cand.get("mint_a_symbol", "")
    b = cand.get("mint_b_symbol", "")
    if a in deny: return {"pass": False, "reason": f"mint_a {a!r} on denylist"}
    if b in deny: return {"pass": False, "reason": f"mint_b {b!r} on denylist"}
    return {"pass": True, "reason": "no denylist hits"}


def filter_no_reward_pool(cand: dict, cfg: dict) -> dict:
    """If set, reject pools with active reward emissions (RAY-10 SDK workaround)."""
    require_no_rewards = bool(cfg.get("reject_reward_emissions", False))
    if not require_no_rewards:
        return {"pass": True, "reason": "rewards filter off"}
    rewards = cand.get("reward_emissions") or []
    active = [r for r in rewards if r and r.get("per_second", 0) > 0]
    if active:
        return {"pass": False,
                "reason": f"{len(active)} active reward emissions (SDK close-bug workaround)"}
    return {"pass": True, "reason": "no active rewards"}


def filter_token_safety(cand: dict, cfg: dict) -> dict:
    """On-chain mint safety (freeze/mint authority, Token-2022 hidden tax / hook).
       DEFAULT OFF — enable via token_safety_enabled. Logic in token_safety.py."""
    from raydium_lp1.token_safety import filter_token_safety as _ts
    return _ts(cand, cfg)


def filter_volume_fee_ratio(cand: dict, cfg: dict) -> dict:
    """Sanity check: 24h volume / TVL ratio shouldn't be absurd."""
    min_ratio = float(cfg.get("min_24h_vol_tvl_ratio", 0.05))
    max_ratio = float(cfg.get("max_24h_vol_tvl_ratio", 50.0))
    tvl = float(cand.get("tvl_usd", 1))
    vol = float(cand.get("volume_24h_usd", 0))
    if tvl <= 0:
        return {"pass": False, "reason": "tvl is zero"}
    ratio = vol / tvl
    if ratio < min_ratio:
        return {"pass": False, "reason": f"vol/tvl {ratio:.2f} < min {min_ratio} (dead pool)"}
    if ratio > max_ratio:
        return {"pass": False, "reason": f"vol/tvl {ratio:.2f} > max {max_ratio} (wash trading?)"}
    return {"pass": True, "reason": f"vol/tvl ratio {ratio:.2f} healthy"}


DEFAULT_CHAIN: list[FilterFn] = [
    filter_pool_age,
    filter_min_tvl,
    filter_max_spread,
    filter_volume_fee_ratio,
    filter_min_apr,
    filter_token_denylist,
    filter_token_allowlist,
    filter_no_reward_pool,
    filter_token_safety,
]


def run_chain(candidate: dict, cfg: dict,
              chain: list[FilterFn] | None = None) -> dict:
    chain = chain or DEFAULT_CHAIN
    for fn in chain:
        try:
            r = fn(candidate, cfg)
        except Exception as e:
            return {"pass": False, "reason": f"filter {fn.__name__} crashed: {e}",
                    "rule": fn.__name__, "candidate": candidate}
        if not r.get("pass"):
            return {"pass": False, "reason": r["reason"],
                    "rule": fn.__name__, "candidate": candidate}
    return {"pass": True, "reason": "all filters passed",
            "rule": "all", "candidate": candidate}


def filter_batch(candidates: list[dict], cfg: dict,
                 chain: list[FilterFn] | None = None,
                 record_rejects: bool = True) -> dict:
    passed: list[dict] = []
    rejected: list[dict] = []
    by_rule: dict[str, int] = {}
    for c in candidates:
        r = run_chain(c, cfg, chain)
        if r["pass"]:
            passed.append(c)
        else:
            rejected.append(r)
            by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1

    if record_rejects and rejected:
        try:
            existing = []
            if REJECT_LOG_PATH.exists():
                with open(REJECT_LOG_PATH, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                    if isinstance(loaded, list):
                        existing = loaded
            ts = time.time()
            for r in rejected:
                existing.append({
                    "ts": ts,
                    "pool_id": r["candidate"].get("pool_id", ""),
                    "rule": r["rule"],
                    "reason": r["reason"],
                    "mint_a": r["candidate"].get("mint_a_symbol", ""),
                    "mint_b": r["candidate"].get("mint_b_symbol", ""),
                })
            existing = existing[-2000:]
            tmp = str(REJECT_LOG_PATH) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            import os; os.replace(tmp, REJECT_LOG_PATH)
        except Exception:
            pass

    return {
        "input": len(candidates),
        "passed": len(passed),
        "rejected": len(rejected),
        "by_rule": by_rule,
        "pass_list": passed,
        "rejects": rejected,
    }


def status() -> dict:
    return {
        "module": "filter_suite",
        "filter_count": len(DEFAULT_CHAIN),
        "filters": [f.__name__ for f in DEFAULT_CHAIN],
        "reject_log": str(REJECT_LOG_PATH),
        "reject_log_exists": REJECT_LOG_PATH.exists(),
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=2))
    else:
        print("usage: filter_suite.py [status]")
        sys.exit(2)
