"""Unified multi-venue LP orchestrator.

ONE pipeline for every venue (Raydium / Kyber-EVM / future GMGN / Kalshi). Each
venue plugs in as a Venue with a scan callable; the orchestrator runs the SAME
defensive stack for all of them:

    scan() -> candidates
      -> filter_suite.run_chain  (chain-aware: Solana token_safety OR EVM GoPlus)
      -> lp_skew_optimizer.optimize_band  (wide-biased band, fee gold-mine logic)
      -> live_guard.guard_onchain  (mode_toggle paper/live + fee_guard escrow caps)
      -> place()  [only in live mode; default no-op placement hook]

This reuses every safety rail already in the repo instead of re-implementing them,
so a new venue = a new Venue entry + a config block. Runs dry-run by default;
on-chain placement is gated behind mode_toggle.is_live() AND a per-venue
`place_fn`, so importing/running this never spends by accident.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from raydium_lp1 import filter_suite
from raydium_lp1.lp_skew_optimizer import optimize_band

REPO = Path(__file__).resolve().parent.parent.parent
RUN_REPORT = REPO / "reports" / "orchestrator_run.json"

# A scan callable takes the venue cfg and returns a list of candidate dicts.
ScanFn = Callable[[dict], list[dict]]
# A place callable takes (candidate, band_plan, cfg) and executes (live only).
PlaceFn = Callable[[dict, dict, dict], dict]


@dataclass
class Venue:
    name: str
    chain_kind: str               # "solana" | "evm" | "copy"
    scan_fn: ScanFn
    cfg: dict = field(default_factory=dict)
    place_fn: PlaceFn | None = None   # None => decision-only (never places)
    # Optional custom filter chain + planner. If None, defaults are used:
    #   filters -> _chain_filters(chain_kind); plan -> LP skew optimizer.
    # Copy-trade / non-LP venues supply their own (e.g. gmgn_venue).
    filters: list | None = None
    plan_fn: Callable[[dict, dict], dict] | None = None


def _chain_filters(chain_kind: str) -> list:
    """Build the filter chain for a venue, swapping in the right token-safety check."""
    base = [
        filter_suite.filter_pool_age,
        filter_suite.filter_min_tvl,
        filter_suite.filter_max_spread,
        filter_suite.filter_volume_fee_ratio,
        filter_suite.filter_min_apr,
        filter_suite.filter_token_denylist,
        filter_suite.filter_token_allowlist,
    ]
    if chain_kind == "evm":
        from raydium_lp1.token_safety_evm import filter_token_safety_evm
        base.append(filter_token_safety_evm)
    else:
        base.append(filter_suite.filter_token_safety)  # Solana mint safety
    return base


def _placement_allowed(operation: str, deposit_sol: float | None) -> tuple[bool, str]:
    """Check mode + fee guard without raising. Returns (allowed, reason)."""
    try:
        from raydium_lp1.live_guard import guard_onchain
        ctx: dict[str, Any] = {}
        if deposit_sol is not None:
            ctx["deposit_sol"] = deposit_sol
        guard_onchain(operation, **ctx)
        return True, "mode=live, fee guard ok"
    except Exception as exc:  # ModeBlockedError / FeeGuardBlockedError / import
        return False, f"{type(exc).__name__}: {exc}"


def run_venue(venue: Venue, *, place: bool = False) -> dict[str, Any]:
    """Scan -> filter -> plan -> (optional) place for one venue."""
    cfg = dict(venue.cfg)
    out: dict[str, Any] = {
        "venue": venue.name, "chain_kind": venue.chain_kind,
        "scanned": 0, "passed": 0, "plans": [], "rejects_by_rule": {}, "placed": [],
    }
    try:
        candidates = list(venue.scan_fn(cfg))
    except Exception as exc:
        out["error"] = f"scan failed: {type(exc).__name__}: {exc}"
        return out
    out["scanned"] = len(candidates)

    chain = venue.filters if venue.filters is not None else _chain_filters(venue.chain_kind)
    batch = filter_suite.filter_batch(candidates, cfg, chain=chain, record_rejects=False)
    out["passed"] = batch["passed"]
    out["rejects_by_rule"] = batch["by_rule"]

    wide_bias = float(cfg.get("lp_wide_bias", 0.35))
    horizon = float(cfg.get("lp_horizon_days", 1.0))
    for cand in batch["pass_list"]:
        if venue.plan_fn is not None:
            rec = dict(venue.plan_fn(cand, cfg))
        else:
            plan = optimize_band(cand, cand.get("momentum"),
                                 wide_bias=wide_bias, horizon_days=horizon)
            rec = {
                "pool_id": cand.get("pool_id") or cand.get("id"),
                "pair": f"{cand.get('mint_a_symbol','?')}/{cand.get('mint_b_symbol','?')}",
                "chosen_width_pct": plan.chosen_width_pct,
                "ev_optimal_width_pct": plan.ev_optimal_width_pct,
                "in_range_prob": plan.in_range_prob,
                "band_vs_spot": {"lower_mult": round(plan.lower_mult, 4),
                                 "upper_mult": round(plan.upper_mult, 4)},
                "rationale": plan.rationale,
            }
        if place and venue.place_fn is not None and rec.get("allow", True):
            deposit_sol = cand.get("deposit_sol") or cfg.get("lp_deposit_sol")
            allowed, why = _placement_allowed(f"{venue.name}:open", deposit_sol)
            if allowed:
                try:
                    rec["placement"] = venue.place_fn(cand, rec, cfg)
                    out["placed"].append(rec.get("pool_id") or rec.get("id"))
                except Exception as exc:
                    rec["placement"] = {"ok": False, "error": str(exc)}
            else:
                rec["placement"] = {"ok": False, "blocked": why}
        out["plans"].append(rec)
    return out


def run(venues: list[Venue], *, place: bool = False, write_report: bool = True) -> dict[str, Any]:
    """Run all venues through the unified pipeline."""
    started = time.time()
    results = [run_venue(v, place=place) for v in venues]
    report = {
        "ts": started,
        "mode": _current_mode(),
        "place_requested": place,
        "venues": results,
        "totals": {
            "scanned": sum(r["scanned"] for r in results),
            "passed": sum(r["passed"] for r in results),
            "plans": sum(len(r["plans"]) for r in results),
            "placed": sum(len(r["placed"]) for r in results),
        },
    }
    if write_report:
        try:
            RUN_REPORT.parent.mkdir(parents=True, exist_ok=True)
            RUN_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError:
            pass
    return report


def _current_mode() -> str:
    try:
        from raydium_lp1.mode_toggle import get_mode
        return get_mode()
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------
# Built-in venue scanners (live data). Add GMGN / Kalshi the same way.
# --------------------------------------------------------------------------

def kyber_evm_scan(cfg: dict) -> list[dict]:
    """Scan Kyber Earn high-APR pools on Base/BNB into candidate dicts."""
    import urllib.parse
    import urllib.request

    chain_id = str(cfg.get("kyber_chain_id", "8453"))   # 8453 base, 56 bnb
    chain_name = "base" if chain_id == "8453" else "bnb"
    api = "https://earn-service.kyberswap.com/api/v1/explorer/pools"
    params = {"chainIds": chain_id, "tag": "high_apr", "sortBy": "apr",
              "orderBy": "DESC", "page": 1, "pageSize": int(cfg.get("kyber_page_size", 20))}
    req = urllib.request.Request(
        f"{api}?{urllib.parse.urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                 "Origin": "https://kyberswap.com"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        body = json.loads(resp.read())
    pools = (body.get("data") or {}).get("pools") or []
    cands: list[dict] = []
    for p in pools:
        toks = p.get("tokens") or []
        t0 = toks[0] if len(toks) > 0 else {}
        t1 = toks[1] if len(toks) > 1 else {}
        cands.append({
            "id": p.get("address"), "pool_id": p.get("address"),
            "mint_a_symbol": t0.get("symbol", "?"), "mint_b_symbol": t1.get("symbol", "?"),
            "token0_address": t0.get("address", ""), "token1_address": t1.get("address", ""),
            "chain": chain_name,
            "tvl_usd": float(p.get("tvl") or 0),
            "liquidity_usd": float(p.get("tvl") or 0),
            "volume_24h_usd": float(p.get("volume1d") or 0),
            "apr_pct": float(p.get("apr") or 0),
            "spread_bps": 0, "age_days": 999,
        })
    return cands


if __name__ == "__main__":
    # Dry-run demo: Kyber Base, decision-only (no placement). EVM token safety on.
    kyber_base = Venue(
        name="kyber-base", chain_kind="evm", scan_fn=kyber_evm_scan,
        cfg={
            "kyber_chain_id": "8453",
            "min_pool_tvl_usd": 1000, "min_apr_pct": 50, "max_spread_bps": 9999,
            "min_pool_age_days": 0, "min_24h_vol_tvl_ratio": 0,
            "evm_token_safety_enabled": True,
            "lp_wide_bias": 0.5, "lp_horizon_days": 1.0,
        },
    )
    report = run([kyber_base], place=False)
    print(json.dumps(report["totals"], indent=2))
    for v in report["venues"]:
        print(f"\n{v['venue']}: scanned={v['scanned']} passed={v['passed']} "
              f"rejects={v['rejects_by_rule']}")
        for plan in v["plans"][:5]:
            print(f"  {plan['pair']:<18} width={plan['chosen_width_pct']}% "
                  f"(EVopt {plan['ev_optimal_width_pct']}%) in-range={plan['in_range_prob']:.0%}")
