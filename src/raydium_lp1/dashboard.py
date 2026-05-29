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

from raydium_lp1 import emergency, health

DEFAULT_DASHBOARD_PATH = Path("reports/dashboard.json")
RECENT_ALERT_COUNT = 5


@dataclass
class DashboardData:
    generated_at: str
    settings: dict
    wallet_capacity: dict
    live_wallet_capacity: dict
    demo_wallet_capacity: dict
    open_positions: list[dict]
    live_open_positions: list[dict]
    demo_simulated_trades: list[dict]
    momentum_hot_top: list[dict]
    recent_alerts: list[dict]
    rpc_health: list[dict]
    last_scan: dict

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "settings": dict(self.settings),
            "wallet_capacity": dict(self.wallet_capacity),
            "live_wallet_capacity": dict(self.live_wallet_capacity),
            "demo_wallet_capacity": dict(self.demo_wallet_capacity),
            "open_positions": list(self.open_positions),
            "live_open_positions": list(self.live_open_positions),
            "demo_simulated_trades": list(self.demo_simulated_trades),
            "momentum_hot_top": list(self.momentum_hot_top),
            "recent_alerts": list(self.recent_alerts),
            "rpc_health": list(self.rpc_health),
            "last_scan": dict(self.last_scan),
        }


def _load_live_positions_file(path: Path | None = None) -> list[dict]:
    path = path or Path("active_positions.json")
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [dict(x) for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        rows = raw.get("positions") or raw.get("open") or []
        if isinstance(rows, list):
            return [dict(x) for x in rows if isinstance(x, dict)]
    return []


def _candidate_to_simulated_trade(candidate: dict, index: int) -> dict:
    mom = candidate.get("momentum") or {}
    h = candidate.get("health") or {}
    a = candidate.get("mint_a_symbol") or ""
    b = candidate.get("mint_b_symbol") or ""
    return {
        "index": index,
        "pool_id": candidate.get("id"),
        "pair": f"{a}/{b}".strip("/"),
        "apr": candidate.get("apr"),
        "liquidity_usd": candidate.get("liquidity_usd"),
        "volume_24h_usd": candidate.get("volume_24h_usd"),
        "health": h.get("score", ""),
        "momentum_score": mom.get("score") or mom.get("combined_score"),
        "momentum_tier": mom.get("tier"),
        "simulated": True,
        "would_execute_in_live": True,
        "action": "would_open_lp",
        "status": "demo_sim",
    }


def _build_demo_wallet_capacity(wallet_capacity: dict, report: dict) -> dict:
    base = dict(wallet_capacity or {})
    cap = dict(base.get("capacity") or {})
    bal = dict(base.get("balance") or {})
    n_pass = int(report.get("candidate_count_pre_capacity") or len(report.get("candidates") or []))
    sim_cap = dict(cap)
    sim_cap["max_positions"] = n_pass
    sim_cap["simulated_slots"] = n_pass
    sim_cap["note"] = (
        "Demo sizing: every pool that passed filters this scan counts as a simulated slot "
        "(not wallet-capped). Same RPC balance read as live."
    )
    return {
        "wallet": base.get("wallet"),
        "balance": bal,
        "capacity": sim_cap,
        "simulated": True,
    }


def _build_live_wallet_capacity(wallet_capacity: dict) -> dict:
    base = dict(wallet_capacity or {})
    cap = dict(base.get("capacity") or {})
    cap = {**cap, "note": "Live wallet: real RPC balance and position slots from funded SOL."}
    return {
        "wallet": base.get("wallet"),
        "balance": dict(base.get("balance") or {}),
        "capacity": cap,
        "simulated": False,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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

    try:
        from raydium_lp1 import mode_toggle

        trading_mode = mode_toggle.get_mode()
    except Exception:
        trading_mode = "demo"

    settings = {
        "strategy": getattr(config, "strategy", "custom"),
        "mode": trading_mode,
        "dry_run": trading_mode == "demo",
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
        "lp_planning_enabled": getattr(config, "lp_planning_enabled", False),
        "lp_active_strategy": getattr(config, "lp_active_strategy", "auto_volatility_pick"),
        "lp_fee_bps": getattr(config, "lp_fee_bps", 25.0),
        "demo_paper_sol": getattr(config, "demo_paper_sol", 10.0),
        "risk_profile": getattr(config, "risk_profile", "balanced"),
        "lp_full_range_parallel": getattr(config, "lp_full_range_parallel", False),
    }

    wallet_capacity = dict(report.get("wallet_capacity") or {})
    live_wallet_capacity = _build_live_wallet_capacity(wallet_capacity)
    settings_for_demo = settings
    try:
        from raydium_lp1.dashboard_enrich import (
            _attach_wallet,
            _build_demo_paper_wallet,
            advance_demo_simulation,
        )
        from raydium_lp1.doctor_advisor import _wallet_runtime

        live_wallet_capacity = _attach_wallet(live_wallet_capacity, _wallet_runtime())
        demo_open, demo_closed, demo_feed = advance_demo_simulation(
            list(report.get("candidates") or []),
            settings=settings_for_demo,
        )
        demo_wallet_capacity = _build_demo_paper_wallet(
            report, settings_for_demo, wallet_capacity, open_positions=demo_open
        )
        demo_simulated_trades = demo_feed
    except Exception:
        demo_wallet_capacity = _build_demo_wallet_capacity(wallet_capacity, report)
        demo_simulated_trades = [
            _candidate_to_simulated_trade(c, i + 1)
            for i, c in enumerate(report.get("candidates") or [])
            if isinstance(c, dict)
        ]
        demo_open, demo_closed = [], []

    live_open_positions = _load_live_positions_file()
    for row in live_open_positions:
        row.setdefault("status", "live")
        row.setdefault("simulated", False)

    positions = list(open_positions) if open_positions is not None else []
    if not positions and not live_open_positions:
        for trade in demo_simulated_trades:
            positions.append(
                {
                    "pool_id": trade.get("pool_id"),
                    "pair": trade.get("pair"),
                    "apr": trade.get("apr"),
                    "liquidity_usd": trade.get("liquidity_usd"),
                    "volume_24h_usd": trade.get("volume_24h_usd"),
                    "health": trade.get("health"),
                    "momentum_score": trade.get("momentum_score"),
                    "momentum_tier": trade.get("momentum_tier"),
                    "dry_run": True,
                }
            )

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
        "scan_mode": report.get("mode"),
        "candidates": list(report.get("candidates") or []),
        "closed_positions": list(report.get("closed_positions") or []),
    }

    return DashboardData(
        generated_at=_now_iso(),
        settings=settings,
        wallet_capacity=wallet_capacity,
        live_wallet_capacity=live_wallet_capacity,
        demo_wallet_capacity=demo_wallet_capacity,
        open_positions=positions,
        live_open_positions=live_open_positions,
        demo_simulated_trades=demo_simulated_trades,
        momentum_hot_top=list(report.get("momentum_hot_top") or []),
        recent_alerts=recent_alerts,
        rpc_health=list(rpc_health or []),
        last_scan=last_scan,
    )


def write_dashboard(data: DashboardData, path: Path = DEFAULT_DASHBOARD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=False keeps rejection histogram / category order meaningful for UI consumers.
    path.write_text(json.dumps(data.to_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8")


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
    lines.append(f"Open positions (dry-run): {len(data.open_positions)}")
    if not data.open_positions:
        lines.append("  (none)")
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
