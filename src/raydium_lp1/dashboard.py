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
    recent_alerts: list[dict]
    rpc_health: list[dict]
    last_scan: dict

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "settings": dict(self.settings),
            "wallet_capacity": dict(self.wallet_capacity),
            "open_positions": list(self.open_positions),
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
        "min_liquidity_usd": getattr(config, "min_liquidity_usd", 0),
        "min_volume_24h_usd": getattr(config, "min_volume_24h_usd", 0),
        "position_size_sol": getattr(config, "position_size_sol", 0.1),
        "reserve_sol": getattr(config, "reserve_sol", 0.02),
        "require_sell_route": getattr(config, "require_sell_route", True),
        "route_sources": list(getattr(config, "route_sources", ())),
        "emergency_close_enabled": getattr(config, "emergency_close_enabled", True),
        "emergency_max_slippage_pct": getattr(config, "emergency_max_slippage_pct", 0.30),
        "estimate_priority_fee_sol": getattr(config, "estimate_priority_fee_sol", 0.00002),
        "network": getattr(config, "network", "solana"),
    }

    wallet_capacity = dict(report.get("wallet_capacity") or {})

    positions = list(open_positions) if open_positions is not None else []
    if not positions:
        # In dry-run we treat candidates as the would-be open positions.
        for candidate in report.get("candidates", [])[: report.get("candidate_count", 0)]:
            h = candidate.get("health") or {}
            positions.append(
                {
                    "pool_id": candidate.get("id"),
                    "pair": f"{candidate.get('mint_a_symbol', '')}/{candidate.get('mint_b_symbol', '')}",
                    "apr": candidate.get("apr"),
                    "liquidity_usd": candidate.get("liquidity_usd"),
                    "volume_24h_usd": candidate.get("volume_24h_usd"),
                    "health": h.get("score", "healthy"),
                    "health_reasons": h.get("reasons", []),
                    "dry_run": True,
                    "shadow_exit_pnl": candidate.get("shadow_exit_pnl"),
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
    lines.append(f"Open positions (dry-run): {len(data.open_positions)}")
    if not data.open_positions:
        lines.append("  (none)")
    for position in data.open_positions:
        lines.append(
            f"  - {position.get('pair', '?'):<20} "
            f"APR {float(position.get('apr', 0) or 0):>7.1f}% "
            f"TVL ${float(position.get('liquidity_usd', 0) or 0):>10,.0f} "
            f"health={position.get('health', 'healthy'):<8} "
            f"pool={position.get('pool_id', '?')}"
        )
        sh = position.get("shadow_exit_pnl") if isinstance(position.get("shadow_exit_pnl"), dict) else {}
        net = sh.get("pnl_sol_net_model")
        if isinstance(net, (int, float)):
            lines.append(
                f"      shadow NET(model) SOL {float(net):+.6f}  "
                f"(entry_assumption {sh.get('entry_assumption_sol')} - priority_reserve "
                f"{sh.get('priority_fee_reserve_sol')}; methodology=probe quotes, not LP remove)"
            )
        elif sh:
            lines.append(f"      shadow exit model: {sh.get('status', '?')} (see shadow_exit_pnl in JSON)")
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
