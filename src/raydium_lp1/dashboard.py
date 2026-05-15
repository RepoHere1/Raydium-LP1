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
            "open_positions": list(self.open_positions),
            "momentum_hot_top": list(self.momentum_hot_top),
            "recent_alerts": list(self.recent_alerts),
            "rpc_health": list(self.rpc_health),
            "last_scan": dict(self.last_scan),
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

    settings = {
        "strategy": getattr(config, "strategy", "custom"),
        "dry_run": getattr(config, "dry_run", True),
        "min_apr": getattr(config, "min_apr", 0),
        "apr_field": getattr(config, "apr_field", "apr24h"),
        "sort_type": getattr(config, "sort_type", "desc"),
        "pool_sort_field": getattr(config, "pool_sort_field", ""),
        "min_liquidity_usd": getattr(config, "min_liquidity_usd", 0),
        "min_volume_24h_usd": getattr(config, "min_volume_24h_usd", 0),
        "position_size_sol": getattr(config, "position_size_sol", 0.1),
        "reserve_sol": getattr(config, "reserve_sol", 0.02),
        "require_sell_route": getattr(config, "require_sell_route", True),
        "route_sources": list(getattr(config, "route_sources", ())),
        "emergency_close_enabled": getattr(config, "emergency_close_enabled", True),
        "emergency_max_slippage_pct": getattr(config, "emergency_max_slippage_pct", 0.30),
        "network": getattr(config, "network", "solana"),
        "momentum_enabled": getattr(config, "momentum_enabled", False),
        "min_momentum_score": getattr(config, "min_momentum_score", 0),
        "momentum_hold_hours": getattr(config, "momentum_hold_hours", 24),
        "momentum_top_hot": getattr(config, "momentum_top_hot", 25),
        "hard_exit_min_tvl_usd": getattr(config, "hard_exit_min_tvl_usd", 0),
    }

    wallet_capacity = dict(report.get("wallet_capacity") or {})

    positions = list(open_positions) if open_positions is not None else []
    if not positions:
        # In dry-run we treat candidates as the would-be open positions.
        for candidate in report.get("candidates", [])[: report.get("candidate_count", 0)]:
            h = candidate.get("health") or {}
            mom = candidate.get("momentum") or {}
            positions.append(
                {
                    "pool_id": candidate.get("id"),
                    "pair": f"{candidate.get('mint_a_symbol', '')}/{candidate.get('mint_b_symbol', '')}",
                    "apr": candidate.get("apr"),
                    "liquidity_usd": candidate.get("liquidity_usd"),
                    "volume_24h_usd": candidate.get("volume_24h_usd"),
                    "health": h.get("score", "healthy"),
                    "health_reasons": h.get("reasons", []),
                    "momentum_score": mom.get("score"),
                    "momentum_tier": mom.get("tier"),
                    "momentum_exit_watch": mom.get("exit_watch"),
                    "dry_run": True,
                }
            )

    recent_alerts = emergency.load_alerts(alerts_path)
    if recent_alerts:
        recent_alerts = recent_alerts[-RECENT_ALERT_COUNT:]

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
    }

    return DashboardData(
        generated_at=_now_iso(),
        settings=settings,
        wallet_capacity=wallet_capacity,
        open_positions=positions,
        momentum_hot_top=list(report.get("momentum_hot_top") or []),
        recent_alerts=recent_alerts,
        rpc_health=list(rpc_health or []),
        last_scan=last_scan,
    )


def write_dashboard(data: DashboardData, path: Path = DEFAULT_DASHBOARD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
