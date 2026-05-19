"""Live market-aware settings optimizer (dry-run discovery focus).

Always analyzes ``reports/dashboard.json`` + the active settings file. When
``settings_optimizer_auto_apply`` is true, merges a bounded patch into settings
after each scan (and when the web UI requests a cycle).

This does **not** guarantee profit — it tightens filters toward high-APR liquid
pools with defensible health based on the latest scan snapshot.
"""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from raydium_lp1.settings_io import load_settings_json, merge_known_settings_patch

DEFAULT_STATE_PATH = Path("reports/settings_optimizer.json")
DEFAULT_SOL_USD = float(os.environ.get("RAYDIUM_LP1_SOL_USD", "150"))

# Keys the optimizer may change when auto-apply is on.
OPTIMIZER_PATCH_KEYS: frozenset[str] = frozenset(
    {
        "min_apr",
        "min_liquidity_usd",
        "min_volume_24h_usd",
        "hard_exit_min_tvl_usd",
        "pages",
        "page_size",
        "pool_sort_field",
        "require_sell_route",
        "sort_candidates_by_apr",
        "sort_candidates_by_momentum",
        "scan_hyper_apr_mode",
        "scan_tune_mode",
        "momentum_enabled",
        "momentum_detective_enabled",
        "emergency_close_enabled",
        "max_route_price_impact_pct",
        "pool_type",
    }
)

SETTINGS_CATALOG: list[dict[str, str]] = [
    {"n": "1", "key": "min_apr", "title": "Min APR %", "detail": "Floor on Raydium day.apr. Higher = fewer pools, usually higher fee APR."},
    {"n": "2", "key": "min_liquidity_usd", "title": "Min TVL (USD)", "detail": "Reject pools below this TVL. Raises exit safety vs dust."},
    {"n": "3", "key": "min_volume_24h_usd", "title": "Min Vol 24h (USD)", "detail": "Requires 24h volume; filters dead markets."},
    {"n": "4", "key": "hard_exit_min_tvl_usd", "title": "Hard reject TVL", "detail": "Red-line TVL; HARD reject message in CSV. 0 = off."},
    {"n": "5", "key": "max_position_usd", "title": "Max position USD", "detail": "Cap per pool notional (dry-run / future wallet cap)."},
    {"n": "6", "key": "apr_field", "title": "APR field key", "detail": "Raydium period for APR (usually apr24h → pool.day.apr)."},
    {"n": "7", "key": "pool_sort_field", "title": "Pool sort field", "detail": "How Raydium pages pools: liquidity (safe) or apr24h (dust on page 1)."},
    {"n": "8", "key": "sort_type", "title": "Sort direction", "detail": "desc = highest metric first."},
    {"n": "9", "key": "pages", "title": "Pages fetched", "detail": "API pages per scan (× page_size pools). More = slower, wider net."},
    {"n": "10", "key": "page_size", "title": "Page size", "detail": "Pools per page (Raydium max ~1000; default 100)."},
    {"n": "11", "key": "pool_type", "title": "pool_type", "detail": "Raydium poolType filter (all, standard, concentrated, …)."},
    {"n": "12", "key": "page_delay_seconds", "title": "Page delay", "detail": "Sleep between Raydium pages (rate limits)."},
    {"n": "13", "key": "http_timeout_seconds", "title": "HTTP timeout", "detail": "Per-request timeout for Raydium/Jupiter HTTP."},
    {"n": "14", "key": "max_pool_age_hours", "title": "Max pool age hrs", "detail": "Skip pools older than N hours (0 = off)."},
    {"n": "15", "key": "min_pool_age_hours", "title": "Min pool age hrs", "detail": "Skip very new pools (rug / launch noise)."},
    {"n": "16", "key": "min_burn_percent", "title": "Min LP burn %", "detail": "Require LP burn % (100 = fully burned)."},
    {"n": "17", "key": "verify_pool_on_chain", "title": "Verify on-chain", "detail": "RPC owner check per pool (slow)."},
    {"n": "18", "key": "verify_pool_raydium_api", "title": "Raydium API verify", "detail": "Extra Raydium verify call."},
    {"n": "19", "key": "require_verified_raydium_pool", "title": "Require verified", "detail": "Reject if verify fails."},
    {"n": "20", "key": "require_pool_id", "title": "Require pool id", "detail": "Reject pools missing pool state id."},
    {"n": "21", "key": "momentum_enabled", "title": "Momentum enabled", "detail": "Score candidates by vol/TVL acceleration."},
    {"n": "22", "key": "min_momentum_score", "title": "Min momentum score", "detail": "Floor on momentum score when required."},
    {"n": "23", "key": "require_momentum_score", "title": "Require momentum", "detail": "Reject without momentum pass."},
    {"n": "24", "key": "momentum_hold_hours", "title": "Momentum hold hrs", "detail": "Bias for hold window in narrative."},
    {"n": "25", "key": "momentum_top_hot", "title": "TOP HOT size", "detail": "Leaderboard size in dashboard."},
    {"n": "26", "key": "sort_candidates_by_momentum", "title": "Sort by momentum", "detail": "Shortlist order: momentum vs APR."},
    {"n": "27", "key": "momentum_min_volume_tvl_ratio", "title": "Min Vol/TVL", "detail": "Momentum filter: activity vs TVL."},
    {"n": "28", "key": "momentum_sweet_min_pool_age_hours", "title": "Sweet min age", "detail": "Momentum age window low."},
    {"n": "29", "key": "momentum_sweet_max_pool_age_hours", "title": "Sweet max age", "detail": "Momentum age window high."},
    {"n": "30", "key": "momentum_min_tvl_usd", "title": "Momentum min TVL", "detail": "Extra TVL floor for momentum path."},
    {"n": "31", "key": "momentum_detective_enabled", "title": "Momentum detective", "detail": "Probe Raydium leaderboards for pulse."},
    {"n": "32", "key": "momentum_probe_market_lists", "title": "Probe market lists", "detail": "Extra list probes (slower)."},
    {"n": "33", "key": "require_sell_route", "title": "Require sell route", "detail": "Jupiter/Raydium exit probe per pool (very slow)."},
    {"n": "34", "key": "use_robust_routing", "title": "Robust routing", "detail": "Multi-source route quality for exits."},
    {"n": "35", "key": "max_route_price_impact_pct", "title": "Max price impact %", "detail": "Reject routes above this impact (30 typical)."},
    {"n": "36", "key": "write_rejections", "title": "Write rejections CSV", "detail": "Export every reject row."},
    {"n": "37", "key": "position_size_sol", "title": "Position SOL", "detail": "SOL notional per LP slot (paper / wallet math)."},
    {"n": "38", "key": "reserve_sol", "title": "Reserve SOL", "detail": "SOL kept aside; lowers max_positions."},
    {"n": "39", "key": "emergency_close_enabled", "title": "Emergency close", "detail": "Alert on critical health; dry-run swap plans."},
    {"n": "40", "key": "emergency_max_slippage_pct", "title": "Emergency slip frac", "detail": "0.30 = 30% max slippage in emergency plans."},
    {"n": "41", "key": "track_liquidity_health", "title": "Track health", "detail": "TVL/volume snapshots → healthy / warning / critical."},
    {"n": "42", "key": "lp_planning_enabled", "title": "LP planning", "detail": "Paper CLMM band suggestions per candidate."},
    {"n": "43", "key": "lp_full_range_parallel", "title": "Parallel full-range", "detail": "Paper second leg: wide/full range hedge."},
    {
        "n": "44",
        "key": "lp_full_range_budget_fraction",
        "title": "Full-range budget frac",
        "detail": "Fraction of position_size_sol for the wide leg (see budget_usd in optimizer). Not USD itself.",
    },
    {
        "n": "45",
        "key": "lp_main_budget_fraction",
        "title": "Main budget frac",
        "detail": "Fraction of position_size_sol for the concentrated band leg.",
    },
    {"n": "46", "key": "lp_max_positions_per_mint", "title": "Max LP / mint", "detail": "Cap concurrent paper slots per token mint."},
    {"n": "47", "key": "scan_tune_mode", "title": "Tune mode", "detail": "Fast TVL sort, no route probes."},
    {"n": "48", "key": "scan_hyper_apr_mode", "title": "Hyper-APR mode", "detail": "Liquid pages + APR-ranked shortlist."},
    {"n": "49", "key": "sort_candidates_by_apr", "title": "Sort by APR", "detail": "Shortlist highest day.apr first."},
    {
        "n": "50",
        "key": "settings_optimizer_auto_apply",
        "title": "Auto-tune (optimizer)",
        "detail": "When true, optimizer writes recommended filters to settings after each scan.",
    },
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def budget_usd_breakdown(settings: Mapping[str, Any], *, sol_usd: float = DEFAULT_SOL_USD) -> dict[str, Any]:
    """Translate LP budget fractions into approximate USD (paper planning)."""

    pos_sol = _f(settings.get("position_size_sol"), 0.1)
    max_usd = _f(settings.get("max_position_usd"), 0.0)
    notional_usd = pos_sol * sol_usd
    if max_usd > 0:
        notional_usd = min(notional_usd, max_usd)
    main_frac = _clamp(_f(settings.get("lp_main_budget_fraction"), 0.75), 0.0, 1.0)
    full_frac = _clamp(_f(settings.get("lp_full_range_budget_fraction"), 0.25), 0.0, 1.0)
    parallel = bool(settings.get("lp_full_range_parallel"))
    main_usd = round(notional_usd * main_frac, 2)
    full_usd = round(notional_usd * full_frac, 2) if parallel else 0.0
    return {
        "sol_usd_assumed": round(sol_usd, 2),
        "position_size_sol": pos_sol,
        "position_notional_usd": round(notional_usd, 2),
        "lp_main_budget_fraction": main_frac,
        "lp_main_budget_usd": main_usd,
        "lp_full_range_budget_fraction": full_frac if parallel else 0.0,
        "lp_full_range_budget_usd": full_usd,
        "lp_full_range_parallel": parallel,
        "formula": "USD ≈ position_size_sol × SOL/USD × fraction (capped by max_position_usd when set)",
        "example": (
            f"0.1 SOL × ${sol_usd:.0f} × 0.25 full-range ≈ ${full_usd:.2f} wide leg; "
            f"0.75 main ≈ ${main_usd:.2f} concentrated (if parallel leg enabled)."
        ),
    }


def _candidate_rows(dashboard: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = list(dashboard.get("candidates") or dashboard.get("open_positions") or [])
    if rows:
        return rows
    return []


def _market_pulse(
    dashboard: Mapping[str, Any],
    settings: Mapping[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    ls = dashboard.get("last_scan") or {}
    scanned = int(ls.get("scanned_count") or 0)
    cands = int(ls.get("candidate_count") or 0)
    rej = int(ls.get("rejected_count") or 0)
    pass_pct = (100.0 * cands / (cands + rej)) if (cands + rej) else 0.0
    hs = ls.get("health_summary") or {}
    crit = int(hs.get("critical") or 0)
    warn = int(hs.get("warning") or 0)
    healthy = int(hs.get("healthy") or 0)

    aprs = [_f(r.get("apr")) for r in rows if _f(r.get("apr")) > 0]
    tvls = [_f(r.get("liquidity_usd")) for r in rows if _f(r.get("liquidity_usd")) > 0]
    vols = [_f(r.get("volume_24h_usd")) for r in rows if _f(r.get("volume_24h_usd")) > 0]
    vol_tvl = [v / t for v, t in zip(vols, tvls) if t > 0]

    med_apr = statistics.median(aprs) if aprs else 0.0
    med_vt = statistics.median(vol_tvl) if vol_tvl else 0.0
    top_apr = max(aprs) if aprs else 0.0

    flow_level = "ok"
    flow_text = "LP flow (vol/TVL) looks active on candidates."
    if med_vt < 0.15:
        flow_level = "warn"
        flow_text = "LP flow is thin — median vol/TVL < 0.15 (churn low vs TVL)."
    if med_vt < 0.05:
        flow_level = "bad"
        flow_text = "LP flow is very weak — median vol/TVL < 0.05."

    apr_level = "ok"
    apr_text = f"APR regime: median candidate {med_apr:.0f}%, top {top_apr:.0f}%."
    if med_apr < 30:
        apr_level = "warn"
        apr_text = f"APR regime is muted — median {med_apr:.0f}% (few hyper pools in your funnel)."

    health_level = "ok"
    health_text = f"Health: {healthy} healthy, {warn} warning, {crit} critical."
    if crit > 0:
        health_level = "bad"
        health_text = f"Health stress — {crit} critical (check Recent alerts)."
    elif warn > 0:
        health_level = "warn"
        health_text = f"Health caution — {warn} warning pool(s); TVL slipping vs entry."

    funnel_level = "ok" if pass_pct >= 5 else "warn"
    if pass_pct < 1:
        funnel_level = "bad"
    funnel_text = f"Funnel pass {pass_pct:.1f}% ({cands}/{scanned} scanned)."

    wallet = dashboard.get("wallet_capacity") or {}
    cap = (wallet.get("capacity") or {}).get("max_positions")
    wallet_level = "ok"
    wallet_text = "Dry-run — wallet not required for scanning."
    if cap is not None and int(cap) <= 0:
        wallet_level = "warn"
        wallet_text = "Wallet capacity max_positions=0 — fund SOL or lower reserve before live slots."

    alerts = dashboard.get("recent_alerts") or []
    alert_level = "ok"
    alert_text = "No recent CRITICAL alerts."
    if any(str(a.get("severity", "")).lower() == "critical" for a in alerts):
        alert_level = "bad"
        alert_text = f"{sum(1 for a in alerts if str(a.get('severity','')).lower()=='critical')} recent CRITICAL alert(s)."

    return [
        {"id": "flow", "label": "Flow", "text": flow_text, "level": flow_level},
        {"id": "apr", "label": "APR", "text": apr_text, "level": apr_level},
        {"id": "health", "label": "Health", "text": health_text, "level": health_level},
        {"id": "funnel", "label": "Funnel", "text": funnel_text, "level": funnel_level},
        {"id": "wallet", "label": "Wallet", "text": wallet_text, "level": wallet_level},
        {"id": "alerts", "label": "Alerts", "text": alert_text, "level": alert_level},
    ][:5]


def _recommend_patch(
    settings: Mapping[str, Any],
    dashboard: Mapping[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    ls = dashboard.get("last_scan") or {}
    cands = int(ls.get("candidate_count") or 0)
    rej = int(ls.get("rejected_count") or 0)
    pass_pct = (100.0 * cands / (cands + rej)) if (cands + rej) else 0.0

    aprs = sorted([_f(r.get("apr")) for r in rows if _f(r.get("apr")) > 0], reverse=True)
    tvls = [_f(r.get("liquidity_usd")) for r in rows if _f(r.get("liquidity_usd")) > 0]
    vols = [_f(r.get("volume_24h_usd")) for r in rows if _f(r.get("volume_24h_usd")) > 0]

    med_apr = statistics.median(aprs) if aprs else 50.0
    p25_tvl = statistics.quantiles(tvls, n=4)[0] if len(tvls) >= 4 else (min(tvls) if tvls else 250_000.0)
    med_vol = statistics.median(vols) if vols else 5000.0

    target_min_apr = _clamp(med_apr * 0.45, 25.0, min(150.0, med_apr * 0.85))
    if aprs and aprs[0] > 200:
        target_min_apr = _clamp(aprs[min(2, len(aprs) - 1)] * 0.35, 40.0, 120.0)

    target_tvl = _clamp(p25_tvl * 0.85, 100_000.0, 2_000_000.0)
    target_vol = _clamp(med_vol * 0.25, 1000.0, 500_000.0)
    target_pages = 10 if cands < 8 else 8 if cands < 15 else 6

    patch: dict[str, Any] = {
        "min_apr": round(target_min_apr, 1),
        "min_liquidity_usd": round(target_tvl, -3),
        "min_volume_24h_usd": round(target_vol, -2),
        "hard_exit_min_tvl_usd": round(max(50_000.0, target_tvl * 0.35), -3),
        "pages": int(target_pages),
        "pool_sort_field": "liquidity",
        "require_sell_route": False,
        "sort_candidates_by_apr": True,
        "sort_candidates_by_momentum": False,
        "scan_hyper_apr_mode": True,
        "scan_tune_mode": False,
        "momentum_enabled": med_apr < 80,
        "momentum_detective_enabled": True,
        "emergency_close_enabled": True,
        "max_route_price_impact_pct": 30.0,
    }
    reasons = {
        "min_apr": f"Median candidate APR ~{med_apr:.0f}% — floor targets upper slice.",
        "min_liquidity_usd": f"~85% of 25th-percentile TVL (${p25_tvl:,.0f}) for exit depth.",
        "min_volume_24h_usd": f"Median vol ~${med_vol:,.0f} — require measurable flow.",
        "pages": f"Pass rate {pass_pct:.1f}% with {cands} candidates — adjust scan breadth.",
        "pool_sort_field": "liquidity paging avoids APR dust page-1.",
        "require_sell_route": "Off for fast discovery; turn on before funded live trading.",
        "sort_candidates_by_apr": "Rank shortlist by Raydium day.apr.",
        "scan_hyper_apr_mode": "Hyper preset aligns with max-APR objective.",
    }
    return patch, reasons


@dataclass
class OptimizerSnapshot:
    updated_at: str
    auto_apply_enabled: bool
    market_pulse: list[dict[str, str]]
    recommended_patch: dict[str, Any]
    patch_reasons: dict[str, str]
    budget_usd: dict[str, Any]
    applied_patch: dict[str, Any]
    last_applied_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "auto_apply_enabled": self.auto_apply_enabled,
            "market_pulse": self.market_pulse,
            "recommended_patch": self.recommended_patch,
            "patch_reasons": self.patch_reasons,
            "budget_usd": self.budget_usd,
            "applied_patch": self.applied_patch,
            "last_applied_at": self.last_applied_at,
            "disclaimer": (
                "Optimizer uses your latest scan only — not a profit guarantee. "
                "Auto-apply writes to settings.json; scanner reloads on next page."
            ),
        }


def analyze(
    *,
    dashboard: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> OptimizerSnapshot:
    rows = _candidate_rows(dashboard)
    pulse = _market_pulse(dashboard, settings, rows)
    patch, reasons = _recommend_patch(settings, dashboard, rows)
    # Only keys we are allowed to auto-touch
    bounded = {k: patch[k] for k in patch if k in OPTIMIZER_PATCH_KEYS}
    if not str(settings.get("pool_type") or "").strip():
        bounded["pool_type"] = "all"
    enabled = bool(settings.get("settings_optimizer_auto_apply", False))
    return OptimizerSnapshot(
        updated_at=_now_iso(),
        auto_apply_enabled=enabled,
        market_pulse=pulse,
        recommended_patch=bounded,
        patch_reasons={k: reasons.get(k, "") for k in bounded},
        budget_usd=budget_usd_breakdown(settings),
        applied_patch={},
        last_applied_at=None,
    )


def write_state(snapshot: OptimizerSnapshot, path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def apply_recommendations(
    snapshot: OptimizerSnapshot,
    settings_path: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Merge recommended_patch into settings when auto_apply or force."""

    if not snapshot.auto_apply_enabled and not force:
        return {}
    try:
        current = load_settings_json(settings_path)
    except (OSError, ValueError):
        return {}
    to_apply: dict[str, Any] = {}
    for key, val in snapshot.recommended_patch.items():
        if key not in OPTIMIZER_PATCH_KEYS:
            continue
        if current.get(key) != val:
            to_apply[key] = val
    if not to_apply:
        return {}
    merge_known_settings_patch(settings_path, to_apply)
    snapshot.applied_patch = to_apply
    snapshot.last_applied_at = _now_iso()
    return to_apply


def run_cycle(
    *,
    settings_path: Path,
    dashboard_path: Path,
    state_path: Path = DEFAULT_STATE_PATH,
) -> OptimizerSnapshot:
    """Analyze latest dashboard + settings; optionally auto-apply."""

    settings: dict[str, Any] = {}
    try:
        settings = load_settings_json(settings_path)
    except (OSError, ValueError):
        pass
    dashboard: dict[str, Any] = {}
    if dashboard_path.exists():
        try:
            raw = json.loads(dashboard_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                dashboard = raw
        except (OSError, json.JSONDecodeError):
            pass
    snap = analyze(dashboard=dashboard, settings=settings)
    applied = apply_recommendations(snap, settings_path)
    if applied:
        snap.patch_reasons = {**snap.patch_reasons, "_applied": f"Wrote {sorted(applied.keys())}"}
    write_state(snap, state_path)
    return snap


def set_auto_apply(enabled: bool, settings_path: Path) -> None:
    merge_known_settings_patch(
        settings_path,
        {"settings_optimizer_auto_apply": bool(enabled)},
    )
