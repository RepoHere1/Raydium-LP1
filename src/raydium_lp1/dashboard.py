"""Unified dashboard output for Raydium-LP1.

Pulls together everything the scanner already produces (settings, wallet
capacity, candidate health, recent alerts, RPC health, last scan) and emits:

* A machine-readable ``reports/dashboard.json`` blob.
* A human-friendly text block printable to the terminal.

The dashboard is rebuilt every scan cycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from raydium_lp1 import emergency, health, pool_verify

DEFAULT_DASHBOARD_PATH = Path("reports/dashboard.json")
SCAN_HEARTBEAT_PATH = Path("reports/scan_heartbeat.json")
SETTINGS_SAVE_ACK_PATH = Path("reports/settings_save_ack.json")
RECENT_ALERT_COUNT = 5


@dataclass
class DashboardData:
    generated_at: str
    settings: dict
    wallet_capacity: dict
    candidates: list[dict]
    open_positions: list[dict]
    momentum_hot_top: list[dict]
    recent_alerts: list[dict]
    rpc_health: list[dict]
    last_scan: dict

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "settings": dict(self.settings),
            "wallet_capacity": dict(self.wallet_capacity),
            "candidates": list(self.candidates),
            "open_positions": list(self.open_positions),
            "momentum_hot_top": list(self.momentum_hot_top),
            "recent_alerts": list(self.recent_alerts),
            "rpc_health": list(self.rpc_health),
            "last_scan": dict(self.last_scan),
        }


def _row_from_candidate(candidate: dict, *, dry_run: bool) -> dict:
    h = candidate.get("health") or {}
    mom = candidate.get("momentum") or {}
    pool_id = str(candidate.get("id") or "")
    program_id = str(candidate.get("program_id") or "")
    return {
        "pool_id": pool_id,
        "pair": f"{candidate.get('mint_a_symbol', '')}/{candidate.get('mint_b_symbol', '')}",
        "mint_a": candidate.get("mint_a", ""),
        "mint_b": candidate.get("mint_b", ""),
        "mint_a_symbol": candidate.get("mint_a_symbol", ""),
        "mint_b_symbol": candidate.get("mint_b_symbol", ""),
        "lp_mint_address": candidate.get("lp_mint_address", ""),
        "market_id": candidate.get("market_id", ""),
        "program_id": program_id,
        "program_label": pool_verify.program_label(program_id) or program_id[:8],
        "pool_type": candidate.get("type", ""),
        "raydium_add_url": pool_verify.raydium_ui_url(pool_id) if pool_id else "",
        "apr": candidate.get("apr"),
        "liquidity_usd": candidate.get("liquidity_usd"),
        "volume_24h_usd": candidate.get("volume_24h_usd"),
        "health": h.get("score", "healthy"),
        "health_reasons": h.get("reasons", []),
        "momentum_score": mom.get("score"),
        "momentum_tier": mom.get("tier"),
        "momentum_exit_watch": mom.get("exit_watch"),
        "dry_run": dry_run,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def simulated_open_slot_count(
    *,
    dry_run: bool,
    max_positions: int,
    candidate_count: int,
    config,
) -> int:
    """How many pools to show under Open positions (simulated wallet slots)."""

    if candidate_count <= 0:
        return 0
    if max_positions > 0:
        return min(candidate_count, max_positions)
    if not dry_run:
        return 0
    # Dry-run with unfunded wallet (max_positions=0): still show a paper-trading preview.
    per_mint = max(1, int(getattr(config, "lp_max_positions_per_mint", 2) or 2))
    preview = max(per_mint * 2, 3)
    return min(candidate_count, preview)


def build_dashboard(
    *,
    config,  # ScannerConfig; avoiding circular import
    report: dict,
    rpc_health: Iterable[dict] | None = None,
    open_positions: Iterable[dict] | None = None,
    alerts_path: Path = emergency.DEFAULT_ALERTS_PATH,
) -> DashboardData:
    """Assemble dashboard data from a scan report + optional position list.

    ``open_positions`` is meant for future use when the bot actually opens
    positions; today the candidate list doubles as the "open in dry-run"
    list so the dashboard still has something to show.
    """

    settings = {
        "strategy": getattr(config, "strategy", "custom"),
        "dry_run": getattr(config, "dry_run", True),
        "network": getattr(config, "network", "solana"),
        "min_apr": getattr(config, "min_apr", 0),
        "apr_field": getattr(config, "apr_field", "apr24h"),
        "sort_type": getattr(config, "sort_type", "desc"),
        "pool_sort_field": getattr(config, "pool_sort_field", ""),
        "pages": getattr(config, "pages", 1),
        "page_size": getattr(config, "page_size", 100),
        "pool_type": getattr(config, "pool_type", "all"),
        "page_delay_seconds": getattr(config, "page_delay_seconds", 0),
        "http_timeout_seconds": getattr(config, "http_timeout_seconds", 15),
        "min_liquidity_usd": getattr(config, "min_liquidity_usd", 0),
        "min_volume_24h_usd": getattr(config, "min_volume_24h_usd", 0),
        "hard_exit_min_tvl_usd": getattr(config, "hard_exit_min_tvl_usd", 0),
        "max_position_usd": getattr(config, "max_position_usd", 0),
        "max_pool_age_hours": getattr(config, "max_pool_age_hours", 0),
        "min_pool_age_hours": getattr(config, "min_pool_age_hours", 0),
        "min_burn_percent": getattr(config, "min_burn_percent", 0),
        "require_momentum_score": getattr(config, "require_momentum_score", False),
        "position_size_sol": getattr(config, "position_size_sol", 0.1),
        "reserve_sol": getattr(config, "reserve_sol", 0.02),
        "require_sell_route": getattr(config, "require_sell_route", True),
        "route_sources": list(getattr(config, "route_sources", ())),
        "max_route_price_impact_pct": getattr(config, "max_route_price_impact_pct", 30.0),
        "use_robust_routing": getattr(config, "use_robust_routing", True),
        "verify_pool_on_chain": getattr(config, "verify_pool_on_chain", True),
        "require_verified_raydium_pool": getattr(config, "require_verified_raydium_pool", True),
        "emergency_close_enabled": getattr(config, "emergency_close_enabled", True),
        "emergency_max_slippage_pct": getattr(config, "emergency_max_slippage_pct", 0.30),
        "momentum_enabled": getattr(config, "momentum_enabled", False),
        "min_momentum_score": getattr(config, "min_momentum_score", 0),
        "momentum_hold_hours": getattr(config, "momentum_hold_hours", 24),
        "momentum_top_hot": getattr(config, "momentum_top_hot", 25),
        "sort_candidates_by_momentum": getattr(config, "sort_candidates_by_momentum", True),
        "sort_candidates_by_apr": getattr(config, "sort_candidates_by_apr", False),
        "scan_tune_mode": getattr(config, "scan_tune_mode", False),
        "scan_hyper_apr_mode": getattr(config, "scan_hyper_apr_mode", False),
        "lp_planning_enabled": getattr(config, "lp_planning_enabled", False),
        "risk_profile": getattr(config, "risk_profile", "balanced"),
        "lp_full_range_parallel": getattr(config, "lp_full_range_parallel", False),
    }

    wallet_capacity = dict(report.get("wallet_capacity") or {})
    dry_run = bool(settings.get("dry_run", True))
    cap = wallet_capacity.get("capacity") if isinstance(wallet_capacity.get("capacity"), dict) else {}
    max_positions = int(cap.get("max_positions") or 0)

    raw_candidates = list(report.get("candidates", [])[: report.get("candidate_count", 0)])
    candidate_rows = [_row_from_candidate(c, dry_run=dry_run) for c in raw_candidates]

    slot_count = simulated_open_slot_count(
        dry_run=dry_run,
        max_positions=max_positions,
        candidate_count=len(candidate_rows),
        config=config,
    )
    if open_positions is not None:
        positions = list(open_positions)
    else:
        positions = candidate_rows[:slot_count]

    if dry_run and max_positions <= 0 and positions:
        wallet_capacity = {
            **wallet_capacity,
            "open_positions_mode": "dry_run_preview",
            "open_positions_preview_count": len(positions),
        }
    elif slot_count > 0:
        wallet_capacity = {**wallet_capacity, "open_positions_mode": "wallet"}

    recent_alerts = emergency.load_alerts(alerts_path)
    if recent_alerts:
        recent_alerts = recent_alerts[-RECENT_ALERT_COUNT:]

    bd = report.get("rejection_breakdown") or {}
    if isinstance(bd, dict):
        breakdown = {str(k): int(v) for k, v in bd.items()}
    else:
        breakdown = {}

    hist = report.get("rejection_reason_histogram") or {}
    if isinstance(hist, dict):
        hist_out = {
            str(k): int(v) for k, v in sorted(hist.items(), key=lambda kv: kv[1], reverse=True)
        }
    else:
        hist_out = {}

    diag = report.get("scan_diagnosis")
    diagnosis_out = diag if isinstance(diag, dict) else {}

    feed = report.get("scan_feed")
    if not isinstance(feed, dict):
        feed = {
            "phase": "complete",
            "page": report.get("pages_total"),
            "pages_total": report.get("pages_total"),
            "is_partial": False,
        }

    last_scan = {
        "scanned_at": report.get("scanned_at"),
        "scanned_count": report.get("scanned_count", 0),
        "candidate_count": report.get("candidate_count", 0),
        "candidate_count_pre_capacity": report.get("candidate_count_pre_capacity"),
        "candidates_truncated": report.get("candidates_truncated", 0),
        "rejected_count": report.get("rejected_count", 0),
        "health_summary": report.get("health_summary", {}),
        "triggered_alerts": report.get("triggered_alerts", []),
        "raydium_api_base": report.get("raydium_api_base"),
        "rejection_breakdown": breakdown,
        "rejection_reason_histogram": hist_out,
        "scan_diagnosis": diagnosis_out,
        "feed": feed,
    }

    return DashboardData(
        generated_at=_now_iso(),
        settings=settings,
        wallet_capacity=wallet_capacity,
        candidates=candidate_rows,
        open_positions=positions,
        momentum_hot_top=list(report.get("momentum_hot_top") or []),
        recent_alerts=recent_alerts,
        rpc_health=list(rpc_health or []),
        last_scan=last_scan,
    )


def write_dashboard(data: DashboardData, path: Path = DEFAULT_DASHBOARD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=False keeps rejection histogram / category order meaningful for UI consumers.
    path.write_text(json.dumps(data.to_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_live_scan_dashboard(
    *,
    config,
    candidates: list[dict],
    scanned_count: int,
    rejected_count: int,
    rejection_breakdown: dict[str, int] | None = None,
    scan_phase: str = "scanning",
    scan_page: int | None = None,
    pages_total: int | None = None,
    raydium_api_base: str = "",
    sort_by_apr: bool = False,
    wallet_capacity: dict | None = None,
    path: Path = DEFAULT_DASHBOARD_PATH,
) -> None:
    """Write ``dashboard.json`` mid-scan so the web UI can show a live candidate feed."""

    cands = list(candidates)
    if sort_by_apr:
        cands.sort(key=lambda p: float(p.get("apr") or 0), reverse=True)

    report: dict = {
        "scanned_at": _now_iso(),
        "scanned_count": scanned_count,
        "candidate_count": len(cands),
        "candidate_count_pre_capacity": len(cands),
        "candidates_truncated": 0,
        "rejected_count": rejected_count,
        "rejection_breakdown": dict(rejection_breakdown or {}),
        "rejection_reason_histogram": {},
        "candidates": cands,
        "health_summary": {},
        "triggered_alerts": [],
        "raydium_api_base": raydium_api_base,
        "momentum_hot_top": [],
        "wallet_capacity": dict(wallet_capacity or {}),
        "scan_diagnosis": {},
        "pages_total": pages_total,
        "scan_feed": {
            "phase": scan_phase,
            "page": scan_page,
            "pages_total": pages_total,
            "is_partial": scan_phase not in {"complete", "scan_complete"},
        },
    }
    data = build_dashboard(config=config, report=report)
    write_dashboard(data, path=path)


def write_scan_heartbeat(
    *,
    phase: str,
    pages_total: int | None = None,
    page: int | None = None,
    scanned_so_far: int = 0,
    candidates_so_far: int = 0,
    rejected_so_far: int = 0,
    pages_failed: int = 0,
    last_error: str | None = None,
    path: Path = SCAN_HEARTBEAT_PATH,
) -> None:
    """Write lightweight scan progress so the web UI can show live/stale state."""

    payload = {
        "updated_at": _now_iso(),
        "phase": phase,
        "pages_total": pages_total,
        "page": page,
        "scanned_so_far": scanned_so_far,
        "candidates_so_far": candidates_so_far,
        "rejected_so_far": rejected_so_far,
        "pages_failed": pages_failed,
        "last_error": last_error,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


def write_settings_save_ack(
    *,
    keys_patched: list[str],
    settings_path: Path,
    path: Path = SETTINGS_SAVE_ACK_PATH,
) -> None:
    payload = {
        "saved_at": _now_iso(),
        "settings_path": str(settings_path.resolve()),
        "keys_patched": list(keys_patched),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


def _hr(char: str = "=", width: int = 64) -> str:
    return char * width


def render_dashboard_text(data: DashboardData) -> str:
    """Render a single human-friendly text block."""

    settings = data.settings
    cap = data.wallet_capacity
    balance = cap.get("balance") or {}
    capacity = cap.get("capacity") or {}
    wallet_info = cap.get("wallet")

    lines: list[str] = []
    lines.append(_hr("="))
    lines.append(f"Raydium-LP1 Dashboard   {data.generated_at}")
    lines.append(_hr("="))

    lines.append("Settings:")
    lines.append(
        f"  strategy={settings.get('strategy', 'custom')} "
        f"| network={settings.get('network', 'solana')} "
        f"| dry_run={settings.get('dry_run', True)}"
    )
    lines.append(
        f"  filters: APR>={settings.get('min_apr', 0):.0f}%, "
        f"TVL>=${settings.get('min_liquidity_usd', 0):,.0f}, "
        f"Vol24h>=${settings.get('min_volume_24h_usd', 0):,.0f}"
    )
    _psort = ((settings.get("pool_sort_field") or "").strip() or settings.get("apr_field", "apr24h"))
    lines.append(
        f"  raydium pages: sorted by {_psort} ({settings.get('sort_type', 'desc')}); "
        f"hard_exit_TVL>={settings.get('hard_exit_min_tvl_usd', 0):,.0f} USD (0=off)"
    )
    if settings.get("lp_planning_enabled"):
        lines.append(
            f"  lp paper plans: ON | risk={settings.get('risk_profile')} "
            f"full_range_parallel={settings.get('lp_full_range_parallel')}"
        )
    if settings.get("momentum_enabled"):
        lines.append(
            f"  momentum: min_score={settings.get('min_momentum_score', 0)} "
            f"hold~{settings.get('momentum_hold_hours', 24):.0f}h "
            f"require_score={settings.get('require_momentum_score', False)}"
        )
    lines.append(
        f"  routes: sources={settings.get('route_sources', [])} require_sell_route={settings.get('require_sell_route')}"
    )
    lines.append(
        f"  emergency: enabled={settings.get('emergency_close_enabled')} "
        f"max_slippage={settings.get('emergency_max_slippage_pct', 0) * 100:.0f}%"
    )

    lines.append("")
    lines.append("Wallet & capacity:")
    if wallet_info:
        lines.append(
            f"  address={wallet_info.get('address', '?')} "
            f"source={wallet_info.get('source', '?')} "
            f"private_key={'set' if wallet_info.get('has_private_key') else 'missing'}"
        )
    else:
        lines.append("  (no wallet configured; set WALLET_ADDRESS in .env)")
    if balance.get("ok"):
        lines.append(
            f"  balance: {balance.get('sol', 0):.6f} SOL ({balance.get('lamports', 0)} lamports) via {balance.get('rpc_url', '?')}"
        )
    elif wallet_info:
        lines.append(f"  balance: UNAVAILABLE ({balance.get('error', 'unknown error')})")
    lines.append(
        f"  position_size={capacity.get('position_size_sol', 0):.4f} SOL "
        f"| reserved={capacity.get('reserved_sol', 0):.4f} SOL "
        f"| max_positions={capacity.get('max_positions', 0)}"
    )

    lines.append("")
    top_n = int(settings.get("momentum_top_hot") or 25)
    lines.append(f"Momentum sniffer — TOP {top_n} HOT (fee-rush targets, live Raydium data):")
    if not data.momentum_hot_top:
        lines.append("  (none this cycle — enable strategy=momentum or lower min_momentum_score)")
    for rank, row in enumerate(data.momentum_hot_top[:top_n], start=1):
        tags = ", ".join((row.get("sniff_tags") or [])[:4])
        lines.append(
            f"  {rank:>2}. {row.get('pair', '?'):<18} "
            f"CMB={float(row.get('combined_score') or 0):>5.0f} "
            f"TVL ${float(row.get('tvl_usd') or 0):>9,.0f} "
            f"VOL ${float(row.get('volume_24h_usd') or 0):>9,.0f} "
            f"APR {float(row.get('apr') or 0):>8.0f}% "
            f"{row.get('tier', '')}"
        )
        if tags:
            lines.append(f"       sniff: {tags}")
        if row.get("exit_watch"):
            lines.append("       !! exit_watch")

    lines.append("")
    lines.append(f"Candidates (scan shortlist): {len(data.candidates)}")
    for row in data.candidates[:15]:
        lines.append(
            f"  - {row.get('pair', '?'):<20} "
            f"APR {float(row.get('apr') or 0):>8.1f}% "
            f"TVL ${float(row.get('liquidity_usd') or 0):>10,.0f} "
            f"pool={row.get('pool_id', '?')}"
        )
    if len(data.candidates) > 15:
        lines.append(f"  … +{len(data.candidates) - 15} more")

    lines.append("")
    lines.append(f"Open positions (simulated wallet slots): {len(data.open_positions)}")
    if not data.open_positions:
        lines.append("  (none — fund SOL / lower reserve, or see Candidates for full shortlist)")
    for position in data.open_positions:
        mom_s = position.get("momentum_score")
        mom_txt = f"MOM={mom_s:.0f} {position.get('momentum_tier', '')}" if mom_s is not None else ""
        lines.append(
            f"  - {position.get('pair', '?'):<20} "
            f"APR {float(position.get('apr', 0) or 0):>7.1f}% "
            f"TVL ${float(position.get('liquidity_usd', 0) or 0):>10,.0f} "
            f"health={position.get('health', 'healthy'):<8} "
            f"{mom_txt} "
            f"pool={position.get('pool_id', '?')}"
        )
        if position.get("momentum_exit_watch"):
            lines.append("      ! momentum/health exit_watch — review before holding LP")
        for reason in position.get("health_reasons", []) or []:
            lines.append(f"      ! {reason}")

    lines.append("")
    lines.append(f"Recent alerts ({len(data.recent_alerts)}):")
    if not data.recent_alerts:
        lines.append("  (none)")
    for alert in data.recent_alerts[-RECENT_ALERT_COUNT:]:
        lines.append(
            f"  - {alert.get('timestamp', '?')} {alert.get('severity', '?').upper():<8} "
            f"{alert.get('pair', '?'):<14} pool={alert.get('pool_id', '?')}"
        )

    lines.append("")
    lines.append(f"RPC health: {len(data.rpc_health)} checked")
    for entry in data.rpc_health:
        mark = "OK" if entry.get("ok") else "FAIL"
        url = entry.get("url", "?")
        err = f" - {entry.get('error')}" if not entry.get("ok") and entry.get("error") else ""
        lines.append(f"  [{mark}] {url}{err}")

    lines.append("")
    lines.append("Last scan:")
    last = data.last_scan
    lines.append(
        f"  at={last.get('scanned_at', '?')} | scanned={last.get('scanned_count', 0)} "
        f"| candidates={last.get('candidate_count', 0)} (pre-cap {last.get('candidate_count_pre_capacity', 0)}) "
        f"| rejected={last.get('rejected_count', 0)}"
    )
    br = last.get("rejection_breakdown") or {}
    if isinstance(br, dict) and br:
        top_cats = sorted(br.items(), key=lambda kv: kv[1], reverse=True)[:8]
        parts = [f"{k}:{v}" for k, v in top_cats]
        lines.append("  rejects by category (top): " + ", ".join(parts))
    summary = last.get("health_summary") or {}
    if summary:
        lines.append(
            f"  health: healthy={summary.get('healthy', 0)} "
            f"warning={summary.get('warning', 0)} "
            f"critical={summary.get('critical', 0)}"
        )
    lines.append(_hr("="))
    return "\n".join(lines)


def print_dashboard(data: DashboardData) -> None:
    print(render_dashboard_text(data))
