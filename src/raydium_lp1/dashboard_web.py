"""Local funnel + settings dashboard (loopback-only HTTP).

GET / serves HTML assembled from web/dashboard_shell.html plus the boot JSON.
GET /dashboard_client.js serves the browser bundle from web/dashboard_client.js.

GET /api/dashboard and GET /api/settings return JSON.
POST /api/settings merges an object into config/settings.json (scanner-known keys only).

Use with::

    python -m raydium_lp1.dashboard_web

and run the scanner with --dashboard --loop --reload-config-each-scan while you tune gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from raydium_lp1.dashboard import DEFAULT_DASHBOARD_PATH
from raydium_lp1.dashboard_field_help import attach_field_help, attach_section_help
from raydium_lp1.doctor_advisor import build_doctor_report, write_doctor_report
from raydium_lp1.tune_advisor import apply_tune_items, build_tune_plan
from raydium_lp1.live_executor import live_readiness_check, open_clmm_candidate
from raydium_lp1.dashboard_scan_runner import scan_status, start_dashboard_scan
from raydium_lp1.live_guard import ModeBlockedError
from raydium_lp1 import mode_toggle
from raydium_lp1.mode_toggle import ModeChangeError
from raydium_lp1.settings_io import load_settings_json, merge_known_settings_patch
from raydium_lp1.lp_strategy_guide import experiment_loop_steps, strategy_cards_for_ui
from raydium_lp1.strategies import ALLOWED_STRATEGIES

DEFAULT_SETTINGS_PATH = Path("config/settings.json")
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_STATIC_DIR = REPO_ROOT / "web"
# Bump when adding HTTP routes so /health can flag stale servers.
API_VERSION = 2
API_FEATURES = (
    "scan_status",
    "scan_run",
    "scan_console",
    "tune",
    "tune_apply",
    "live_readiness",
    "live_open",
    "super_brainiac",
    "doctor",
    "mode",
)
WEB_SCAN_CONSOLE_LOG = REPO_ROOT / "reports" / "web_scan_console.log"
DASHBOARD_SHELL_HTML = WEB_STATIC_DIR / "dashboard_shell.html"
DASHBOARD_CLIENT_JS = WEB_STATIC_DIR / "dashboard_client.js"


def _static_mime(path: Path) -> str:
    if path.suffix.lower() == ".html":
        return "text/html; charset=utf-8"
    if path.suffix.lower() == ".css":
        return "text/css; charset=utf-8"
    if path.suffix.lower() == ".js":
        return "application/javascript; charset=utf-8"
    return "application/octet-stream"


def pool_link(pool_id: str, source: str | None = None) -> str:
    pid = (pool_id or "").strip()
    if not pid:
        return ""
    s = (source or "").lower()
    href = "https://raydium.io/portfolio/?position_tab=standard"
    if "dexscreener" in s:
        href = f"https://dexscreener.com/solana/{pid}"
    elif "raydium" in s:
        href = "https://raydium.io/portfolio/?position_tab=standard"
    short = pid[:4] + "..." + pid[-4:] if len(pid) > 12 else pid
    return f'<a class="pool-pill" href="{href}" target="_blank" rel="noopener noreferrer" title="{pid}" data-copy="{pid}"><code>{short}</code></a>'


def health_class(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in ("critical", "red", "bad"):
        return "crit"
    if v in ("warning", "warn", "yellow"):
        return "warn"
    return "ok"


def cell(cls: str, value: str) -> str:
    return f'<td class="{cls}">{value}</td>'


def render_table_header() -> str:
    return "".join([
        "<thead><tr>",
        "<th>Pair</th>",
        "<th>APR</th>",
        "<th>%TVL</th>",
        "<th>TVL</th>",
        "<th>Vol24</th>",
        "<th>Health</th>",
        "<th>Mom</th>",
        "<th>Pool id</th>",
        "</tr></thead>",
    ])


def paginate_rows(rows: list[dict[str, Any]], page: int, page_size: int = 30) -> list[dict[str, Any]]:
    page = max(1, int(page or 1))
    page_size = max(1, int(page_size or 30))
    start = (page - 1) * page_size
    end = start + page_size
    return rows[start:end]


def render_table_rows(rows: list[dict[str, Any]]) -> str:
    return "".join(render_pool_row(row) for row in rows)


def render_table_rows_live(rows: list[dict[str, Any]], page: int = 1, page_size: int = 30) -> str:
    return render_table_rows(paginate_rows(rows, page, page_size))


def render_table_rows_demo(rows: list[dict[str, Any]], page: int = 1, page_size: int = 30) -> str:
    return render_table_rows(paginate_rows(rows, page, page_size))


def render_pool_row(row: dict[str, Any]) -> str:
    return "".join(render_pool_row(row) for row in rows)


def render_table_rows_live(rows: list[dict[str, Any]]) -> str:
    return render_table_rows(rows)


def render_table_rows_demo(rows: list[dict[str, Any]]) -> str:
    return render_table_rows(rows)


def render_pool_row(row: dict[str, Any]) -> str:
    pair = str(row.get("pair", ""))
    apr = float(row.get("apr", 0) or 0)
    tvl = float(row.get("liquidity_usd", 0) or 0)
    vol24 = float(row.get("volume_24h_usd", 0) or 0)
    mom = float(row.get("momentum_score", 0) or 0)
    tvl_pct = float(row.get("tvl_pct", row.get("percent_tvl", 0)) or 0)
    health_raw = row.get("health")
    health_value = (health_raw or {}).get("score") if isinstance(health_raw, dict) else health_raw
    health_label = str(row.get("health_label", health_value or ""))
    health_cls = health_class(health_value if health_value is not None else health_label)
    pair_cls = "pair ok"
    if health_cls == "warn":
        pair_cls = "pair warn"
    elif health_cls == "crit":
        pair_cls = "pair crit"
    return "".join([
        cell(pair_cls, pair),
        cell("apr ok" if apr >= 0 else "apr", f"{apr:.2f}"),
        cell("tvl ok" if tvl >= 0 else "tvl", f"{tvl:,.0f}"),
        cell("tvlpct ok" if tvl_pct >= 0 else "tvlpct", f"{tvl_pct:.2f}"),
        cell("vol24 ok" if vol24 >= 0 else "vol24", f"{vol24:,.0f}"),
        cell(f"health {health_cls}", health_label),
        cell("mom ok" if mom >= 0 else "mom", f"{mom:.2f}"),
        cell("poolid", pool_addr_html),
    ])


def health_class(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in ("critical", "red", "bad"):
        return "crit"
    if v in ("warning", "warn", "yellow"):
        return "warn"
    return "ok"


def cell(cls: str, value: str) -> str:
    return f'<td class="{cls}">{value}</td>'


def render_table_header() -> str:
    return "".join([
        "<thead><tr>",
        "<th>Pair</th>",
        "<th>APR</th>",
        "<th>%TVL</th>",
        "<th>TVL</th>",
        "<th>Vol24</th>",
        "<th>Health</th>",
        "<th>Mom</th>",
        "<th>Pool id</th>",
        "</tr></thead>",
    ])


def paginate_rows(rows: list[dict[str, Any]], page: int, page_size: int = 30) -> list[dict[str, Any]]:
    page = max(1, int(page or 1))
    page_size = max(1, int(page_size or 30))
    start = (page - 1) * page_size
    end = start + page_size
    return rows[start:end]


def render_table_rows(rows: list[dict[str, Any]]) -> str:
    return "".join(render_pool_row(row) for row in rows)


def render_table_rows_live(rows: list[dict[str, Any]], page: int = 1, page_size: int = 30) -> str:
    return render_table_rows(paginate_rows(rows, page, page_size))


def render_table_rows_demo(rows: list[dict[str, Any]], page: int = 1, page_size: int = 30) -> str:
    return render_table_rows(paginate_rows(rows, page, page_size))


def render_pool_row(row: dict[str, Any]) -> str:
    return "".join(render_pool_row(row) for row in rows)


def render_table_rows_live(rows: list[dict[str, Any]]) -> str:
    return render_table_rows(rows)


def render_table_rows_demo(rows: list[dict[str, Any]]) -> str:
    return render_table_rows(rows)


def render_pool_row(row: dict[str, Any]) -> str:
    pair = str(row.get("pair", ""))
    apr = float(row.get("apr", 0) or 0)
    tvl = float(row.get("liquidity_usd", 0) or 0)
    vol24 = float(row.get("volume_24h_usd", 0) or 0)
    mom = float(row.get("momentum_score", 0) or 0)
    tvl_pct = float(row.get("tvl_pct", row.get("percent_tvl", 0)) or 0)
    health_raw = row.get("health")
    health_value = (health_raw or {}).get("score") if isinstance(health_raw, dict) else health_raw
    health_label = str(row.get("health_label", health_value or ""))
    health_cls = health_class(health_value if health_value is not None else health_label)
    pair_cls = "pair ok"
    if health_cls == "warn":
        pair_cls = "pair warn"
    elif health_cls == "crit":
        pair_cls = "pair crit"
    return "".join([
        cell(pair_cls, pair),
        cell("apr ok" if apr >= 0 else "apr", f"{apr:.2f}"),
        cell("tvl ok" if tvl >= 0 else "tvl", f"{tvl:,.0f}"),
        cell("tvlpct ok" if tvl_pct >= 0 else "tvlpct", f"{tvl_pct:.2f}"),
        cell("vol24 ok" if vol24 >= 0 else "vol24", f"{vol24:,.0f}"),
        cell(f"health {health_cls}", health_label),
        cell("mom ok" if mom >= 0 else "mom", f"{mom:.2f}"),
        cell("poolid", pool_addr_html),
    ])


def health_class(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in ("critical", "red", "bad"):
        return "crit"
    if v in ("warning", "warn", "yellow"):
        return "warn"
    return "ok"


def cell(cls: str, value: str) -> str:
    return f'<td class="{cls}">{value}</td>'

def _serve_repo_static(url_path: str) -> tuple[bytes, str] | None:
    files: dict[str, Path] = {
        "/positions.html": WEB_STATIC_DIR / "positions.html",
        "/index.html": WEB_STATIC_DIR / "index.html",
        "/styles.css": REPO_ROOT / "styles.css",
        "/dashboard_client.js": DASHBOARD_CLIENT_JS,
        "/mode_shared.js": WEB_STATIC_DIR / "mode_shared.js",
        "/positions_client.js": WEB_STATIC_DIR / "positions_client.js",
        "/lp1_copy.js": WEB_STATIC_DIR / "lp1_copy.js",
    }
    if url_path not in files:
        return None
    target = files[url_path]
    if not target.is_file():
        return None
    return target.read_bytes(), _static_mime(target)


_FORM_SECTIONS: list[dict[str, Any]] = [
    {
        "title": "Liquidity gates",
        "fields": [
            {"key": "min_apr", "label": "Min APR %", "type": "number", "step": "any"},
            {"key": "min_liquidity_usd", "label": "Min TVL (USD)", "type": "number", "step": "any"},
            {"key": "min_volume_24h_usd", "label": "Min Vol 24h (USD)", "type": "number", "step": "any"},
            {"key": "hard_exit_min_tvl_usd", "label": "hard_exit_min_tvl_usd (USD)", "type": "number", "step": "any"},
            {"key": "max_position_usd", "label": "Max position USD", "type": "number", "step": "any"},
        ],
    },
    {
        "title": "Raydium paging",
        "fields": [
            {"key": "apr_field", "label": "APR field key", "type": "text"},
            {"key": "pool_sort_field", "label": "Pool sort field", "type": "text"},
            {"key": "sort_type", "label": "Sort direction", "type": "select", "options": ["desc", "asc"]},
            {"key": "pages", "label": "Pages fetched", "type": "number"},
            {"key": "page_size", "label": "Page size", "type": "number"},
            {"key": "pool_type", "label": "pool_type", "type": "text"},
            {"key": "page_delay_seconds", "label": "Page delay (s)", "type": "number", "step": "any"},
            {"key": "http_timeout_seconds", "label": "HTTP timeout", "type": "number"},
        ],
    },
    {
        "title": "Age, burn, verification",
        "fields": [
            {"key": "max_pool_age_hours", "label": "Max pool age hrs (0=off)", "type": "number", "step": "any"},
            {"key": "min_pool_age_hours", "label": "Min pool age hrs", "type": "number", "step": "any"},
            {"key": "min_burn_percent", "label": "Min LP burn %", "type": "number", "step": "any"},
            {"key": "verify_pool_on_chain", "label": "Verify pool on-chain", "type": "checkbox"},
            {"key": "verify_pool_raydium_api", "label": "Raydium API verify", "type": "checkbox"},
            {"key": "require_verified_raydium_pool", "label": "Require verified Raydium pool", "type": "checkbox"},
            {"key": "require_pool_id", "label": "Require pool id", "type": "checkbox"},
        ],
    },
    {
        "title": "Momentum",
        "fields": [
            {"key": "momentum_enabled", "label": "Momentum enabled", "type": "checkbox"},
            {"key": "min_momentum_score", "label": "Min momentum score", "type": "number", "step": "any"},
            {"key": "require_momentum_score", "label": "Require momentum score pass", "type": "checkbox"},
            {"key": "momentum_hold_hours", "label": "Hold window hrs", "type": "number", "step": "any"},
            {"key": "momentum_top_hot", "label": "TOP HOT size", "type": "number"},
            {
                "key": "momentum_hot_min_combined_score",
                "label": "HOT min combined score",
                "type": "number",
                "step": "any",
            },
            {
                "key": "momentum_hot_min_apr",
                "label": "HOT min APR %",
                "type": "number",
                "step": "any",
            },
            {"key": "sort_candidates_by_momentum", "label": "Sort candidates by momentum", "type": "checkbox"},
            {
                "key": "lp_selection_mode",
                "label": "LIVE LP pick mode (apr | momentum)",
                "type": "select",
                "options": ["apr", "momentum"],
            },
            {"key": "momentum_min_volume_tvl_ratio", "label": "Min Vol/TVL ratio", "type": "number", "step": "any"},
            {"key": "momentum_sweet_min_pool_age_hours", "label": "Sweet min pool age hrs", "type": "number", "step": "any"},
            {"key": "momentum_sweet_max_pool_age_hours", "label": "Sweet max pool age hrs", "type": "number", "step": "any"},
            {"key": "momentum_min_tvl_usd", "label": "Momentum min TVL USD", "type": "number", "step": "any"},
            {"key": "momentum_detective_enabled", "label": "Momentum detective", "type": "checkbox"},
            {"key": "momentum_probe_market_lists", "label": "Probe market lists", "type": "checkbox"},
        ],
    },
    {
        "title": "Routes and reporting",
        "fields": [
            {"key": "require_sell_route", "label": "Require sell route", "type": "checkbox"},
            {"key": "use_robust_routing", "label": "Robust routing", "type": "checkbox"},
            {"key": "max_route_price_impact_pct", "label": "Max quote price impact %", "type": "number", "step": "any"},
            {"key": "route_sources_json", "label": "Rejection reasons / route sources (JSON array)", "type": "json_text"},
            {"key": "write_rejections", "label": "Write rejections CSV", "type": "checkbox"},
            {"key": "rejections_csv_path", "label": "Rejections CSV path", "type": "text"},
        ],
    },
    {
        "title": "Wallet and emergency",
        "fields": [
            {"key": "position_size_sol", "label": "Position SOL", "type": "number", "step": "any"},
            {"key": "reserve_sol", "label": "Reserve SOL", "type": "number", "step": "any"},
            {
                "key": "wallet_address",
                "label": "Wallet Address",
                "type": "text",
                "help": "Public key for RPC balance reads. Prefer scripts/import_wallet.ps1 to sync .env and this file.",
                "live_hint": "Must match WALLET_ADDRESS in .env for live mode.",
            },
            {"key": "emergency_close_enabled", "label": "Emergency close", "type": "checkbox"},
            {"key": "emergency_max_slippage_pct", "label": "Emergency max slip (0-1 frac)", "type": "number", "step": "any"},
            {"key": "emergency_base_symbol", "label": "Emergency base symbol", "type": "text"},
            {"key": "emergency_alerts_path", "label": "Alerts path", "type": "text"},
            {"key": "emergency_route_watch_enabled", "label": "Route watch (5×/24h)", "type": "checkbox"},
            {"key": "emergency_route_checks_per_day", "label": "Route checks per 24h", "type": "number", "step": "1"},
            {"key": "track_liquidity_health", "label": "Track liquidity health", "type": "checkbox"},
            {"key": "liquidity_history_path", "label": "Liquidity history path", "type": "text"},
        ],
    },
    {
        "title": "Fee guard (on-chain spend)",
        "section_id": "fee_guard",
        "section_help": (
            "Mandatory caps so Raydium CLMM rent + priority fees cannot drain the wallet on micro-deposits "
            "or retry loops. 25¢ LP opens are blocked by design."
        ),
        "section_rec": (
            "Leave enabled. If you lost SOL to fees, check reports/fee_session_ledger.json. "
            "Use min_clmm_deposit_sol ≥ 0.008 and max_open_retries = 1."
        ),
        "fields": [
            {"key": "fee_guard_enabled", "label": "Fee guard enabled", "type": "checkbox"},
            {"key": "min_clmm_deposit_sol", "label": "Min CLMM deposit (SOL)", "type": "number", "step": "any"},
            {"key": "max_priority_fee_micro_lamports", "label": "Max priority fee (µ-lamports/CU)", "type": "number"},
            {"key": "max_open_retries", "label": "Max open attempts per click", "type": "number"},
            {"key": "max_session_spend_sol", "label": "Max session spend est. (SOL)", "type": "number", "step": "any"},
            {"key": "max_fee_pct_of_deposit", "label": "Max fee+rent % of deposit", "type": "number", "step": "any"},
            {"key": "max_rent_escrow_pct_of_deposit", "label": "Max sunk rent % of deposit", "type": "number", "step": "any"},
            {"key": "clmm_open_rent_sol", "label": "Est. CLMM open rent (SOL)", "type": "number", "step": "any"},
        ],
    },
    {
        "title": "LP order entry (CLMM)",
        "section_id": "lp_order_entry",
        "section_help": (
            "How Raydium concentrated liquidity positions are opened on the next LIVE deposit "
            "(and how DRY_RUN plans bands). Each card maps to lp_active_strategy in settings.json."
        ),
        "section_rec": (
            "Experiment loop: pick style → save → small LIVE → compare LP style stats → repeat. "
            "Default volatility_atr_width or auto_volatility_pick for meme scans."
        ),
        "fields": [
            {
                "key": "lp_active_strategy",
                "label": "LP order entry style",
                "type": "strategy_picker",
            },
            {"key": "lp_skew_use_momentum", "label": "Skew bands via momentum (trailing / asymmetric)", "type": "checkbox"},
            {
                "key": "lp_open_pay_token_only",
                "label": "Pay-token-only LP opens (SOL/USDC/USDT deposit)",
                "type": "checkbox",
            },
            {
                "key": "lp_pay_prefer_symbol",
                "label": "Preferred pay symbol (blank = emergency_base_symbol)",
                "type": "text",
            },
            {"key": "lp_default_range_width_pct", "label": "Default band width %", "type": "number", "step": "any"},
            {"key": "lp_planning_enabled", "label": "LP planning in scan output", "type": "checkbox"},
            {"key": "lp_fee_bps", "label": "Pool fee tier (bps)", "type": "number", "step": "any"},
            {"key": "demo_paper_sol", "label": "DRY_RUN paper SOL balance", "type": "number", "step": "any"},
            {"key": "lp_range_mode", "label": "Range width mode (legacy)", "type": "text"},
            {"key": "lp_range_width_candidates_json", "label": "Band width candidates JSON", "type": "json_text"},
            {"key": "lp_full_range_parallel", "label": "Parallel full-range paper leg", "type": "checkbox"},
            {"key": "lp_full_range_budget_fraction", "label": "Full-range budget fraction", "type": "number", "step": "any"},
            {"key": "lp_main_budget_fraction", "label": "Main band budget fraction", "type": "number", "step": "any"},
            {"key": "lp_max_positions_per_mint", "label": "Max LP positions per mint", "type": "number"},
            {
                "key": "manual_live_min_pool_liquidity_usd",
                "label": "Manual LIVE: min pool TVL ($)",
                "type": "number",
                "step": "any",
            },
            {
                "key": "manual_live_require_sell_route",
                "label": "Manual LIVE: require alt sell route",
                "type": "checkbox",
            },
            {
                "key": "manual_live_max_route_price_impact_pct",
                "label": "Manual LIVE: route max impact % (0 = global)",
                "type": "number",
                "step": "any",
            },
            {
                "key": "manual_live_alerts_path",
                "label": "Manual LIVE: block alerts path",
                "type": "text",
            },
        ],
    },
    {
        "title": "SUPER-BRAINIAC_POSSIBILITIES (experiment)",
        "section_id": "super_brainiac",
        "section_help": (
            "Experimental fee-capture detective: scans CLMM pools with $5k+ TVL and two-way routes, "
            "scores all LP order styles, optionally opens the top pick for a small deposit."
        ),
        "section_rec": (
            "Start with scan-only; enable auto_open only when you accept unattended LIVE. "
            "Target APR 999.99 is a ranking label — real fee $ matters more."
        ),
        "fields": [
            {"key": "super_brainiac_enabled", "label": "Experiment enabled", "type": "checkbox"},
            {"key": "super_brainiac_min_liquidity_usd", "label": "Min pool TVL ($)", "type": "number", "step": "any"},
            {"key": "super_brainiac_deposit_usd", "label": "Experiment deposit ($)", "type": "number", "step": "any"},
            {"key": "super_brainiac_target_apr_pct", "label": "Target APR % (ranking label)", "type": "number", "step": "any"},
            {"key": "super_brainiac_auto_open_live", "label": "Auto LIVE open top pick", "type": "checkbox"},
            {"key": "super_brainiac_scan_pages", "label": "Scan pages", "type": "number"},
            {"key": "super_brainiac_prefer_fee_pct_min", "label": "Prefer fee % min", "type": "number", "step": "any"},
            {"key": "super_brainiac_prefer_fee_pct_max", "label": "Prefer fee % max", "type": "number", "step": "any"},
            {"key": "super_brainiac_require_buy_route", "label": "Require buy routes", "type": "checkbox"},
            {"key": "super_brainiac_require_sell_route", "label": "Require sell routes", "type": "checkbox"},
            {"key": "super_brainiac_min_confidence", "label": "Min confidence to open", "type": "number", "step": "any"},
            {"key": "super_brainiac_continuous_interval_sec", "label": "Loop interval (sec)", "type": "number", "step": "any"},
            {"key": "super_brainiac_report_path", "label": "Report JSON path", "type": "text"},
            {
                "key": "super_brainiac_require_pay_alt_pair_only",
                "label": "PAY/ALT pairs only (no SOL/USDC)",
                "type": "checkbox",
            },
            {"key": "spend_less_get_more_enabled", "label": "SPEND LESS=GET MORE enabled", "type": "checkbox"},
            {"key": "spend_less_auto_clamp_deposit", "label": "Auto-clamp deposit to affordable", "type": "checkbox"},
            {"key": "spend_less_auto_fallback_from_wide", "label": "Wide→single-sided fallback", "type": "checkbox"},
            {"key": "spend_less_on_chain_rent_buffer_sol", "label": "SOL rent buffer (SOL pay)", "type": "number", "step": "any"},
        ],
    },
    {
        "title": "Network metadata",
        "fields": [
            {"key": "strategy", "label": "strategy", "type": "select", "options": list(ALLOWED_STRATEGIES)},
            {"key": "network", "label": "network", "type": "text"},
            {"key": "risk_profile", "label": "risk_profile", "type": "text"},
            {"key": "mode", "label": "Trading mode (dry_run|live)", "type": "text"},
            {"key": "dry_run", "label": "Dry Run (synced with mode)", "type": "checkbox"},
            {"key": "raydium_api_base", "label": "Raydium API base", "type": "text"},
            {"key": "solana_rpc_urls_lines", "label": "RPC URLs (one per line)", "type": "lines"},
            {"key": "allowed_quote_symbols_csv", "label": "Allowed quotes CSV", "type": "csv"},
            {"key": "blocked_token_symbols_csv", "label": "Blocked symbols CSV", "type": "csv"},
            {"key": "blocked_mints_lines", "label": "Blocked mints lines", "type": "lines"},
            {"key": "dashboard_path", "label": "Dashboard JSON path", "type": "text"},
            {"key": "scan_loop", "label": "scan_loop (prefer CLI)", "type": "checkbox"},
            {"key": "scan_loop_interval_seconds", "label": "Loop interval hint (s)", "type": "number"},
            {"key": "spawn_verdict_watcher", "label": "Spawn verdict watcher", "type": "checkbox"},
        ],
    },
]

attach_field_help(_FORM_SECTIONS)
attach_section_help(_FORM_SECTIONS)


@dataclass(frozen=True)
class WebPaths:
    dashboard_path: Path
    settings_path: Path


def _normalize_settings_mode_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Align ``mode`` and ``dry_run`` in a settings POST body."""

    pk = dict(patch)
    if "mode" in pk and "dry_run" not in pk:
        pk["dry_run"] = str(pk["mode"]).lower().strip() == "demo"
    elif "dry_run" in pk and "mode" not in pk:
        pk["mode"] = "demo" if bool(pk.get("dry_run")) else "live"
    return pk


def _apply_settings_mode_change(
    settings_path: Path,
    patch: dict[str, Any],
    *,
    source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Use ``mode_toggle.set_mode`` when POST would change trading mode; strip mode keys from merge."""

    if "mode" not in patch and "dry_run" not in patch:
        return patch, None

    pk = mode_toggle.sync_mode_fields(dict(patch))
    target = str(pk.get("mode", mode_toggle.get_mode())).lower()
    current = mode_toggle.get_mode()
    result: dict[str, Any] | None = None

    if target != current:
        if target == "live":
            confirm = pk.pop("confirm", patch.get("confirm"))
            result = mode_toggle.set_mode("live", confirm=confirm, source=source)
        else:
            result = mode_toggle.set_mode("demo", source=source)

    for key in ("mode", "dry_run", "confirm"):
        pk.pop(key, None)
    return pk, result


def _page() -> bytes:
    if not DASHBOARD_SHELL_HTML.is_file():
        raise RuntimeError(f"Dashboard UI shell missing: {DASHBOARD_SHELL_HTML}.")
    shell = DASHBOARD_SHELL_HTML.read_text(encoding="utf-8")
    if "BOOT_JSON" not in shell:
        raise RuntimeError(f"{DASHBOARD_SHELL_HTML} must contain the BOOT_JSON placeholder")
    boot_payload = {
        "form_sections": _FORM_SECTIONS,
        "lp_strategy_cards": strategy_cards_for_ui(),
        "lp_experiment_loop": experiment_loop_steps(),
        "table_page_size": 30,
        "mode_tabs": ["LIVE", "DRY_RUN"],
        "status_fields": ["last_scan_utc", "scan_sequence", "candidate_count", "position_count"],
    }
    html = shell.replace("BOOT_JSON", json.dumps(boot_payload, separators=(",", ":")))
    raw = html.encode("utf-8")
    if b"<<<<<<<" in raw or b">>>>>>>" in raw:
        raise RuntimeError("dashboard shell contains git merge conflict markers")
    if DASHBOARD_CLIENT_JS.is_file():
        js_bytes = DASHBOARD_CLIENT_JS.read_bytes()
        if b"<<<<<<<" in js_bytes or b">>>>>>>" in js_bytes:
            raise RuntimeError("dashboard_client.js contains git merge conflict markers")
    return raw


def main(argv: list[str] | None = None) -> int:
    import urllib.parse as up

    parser = argparse.ArgumentParser(description="Raydium-LP1 local dashboard (127.0.0.1 only).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8844)
    parser.add_argument("--dashboard", type=Path, default=DEFAULT_DASHBOARD_PATH)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS_PATH)
    args = parser.parse_args(argv)

    paths = WebPaths(dashboard_path=args.dashboard, settings_path=args.settings)
    blob = {"page": _page()}

    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if "html" in ctype or "javascript" in ctype:
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, obj: Any) -> None:
            raw = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            self._send(code, raw, "application/json; charset=utf-8")

        def do_GET(self) -> None:
            path = up.urlparse(self.path).path.rstrip("/") or "/"
            static = _serve_repo_static(path)
            if static is not None:
                body, ctype = static
                self._send(200, body, ctype)
                return
            if path == "/":
                self._send(200, blob["page"], "text/html; charset=utf-8")
                return
            if path == "/api/dashboard":
                dpath = paths.dashboard_path
                if not dpath.exists():
                    self._send_json(404, {"error": f"Dashboard not found: {dpath}"})
                    return
                try:
                    data = json.loads(dpath.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                try:
                    from raydium_lp1.dashboard_enrich import enrich_dashboard_payload

                    data = enrich_dashboard_payload(data, paths.settings_path)
                except Exception as exc:
                    data["feed_enrich_error"] = str(exc)
                self._send_json(200, data)
                return
            if path == "/api/settings":
                try:
                    data = load_settings_json(paths.settings_path)
                except (OSError, ValueError) as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, data)
                return
            if path == "/api/runtime":
                from raydium_lp1.doctor_advisor import _wallet_runtime

                payload = {**mode_toggle.status(), "wallet": _wallet_runtime()}
                self._send_json(200, payload)
                return
            if path == "/api/doctor":
                try:
                    report = build_doctor_report(
                        settings_path=paths.settings_path,
                        latest_path=paths.dashboard_path.parent / "latest.json",
                        include_structural=True,
                    )
                    write_doctor_report()
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, report)
                return
            if path == "/api/tune":
                try:
                    plan = build_tune_plan(
                        latest_path=paths.dashboard_path.parent / "latest.json",
                        settings_path=paths.settings_path,
                    )
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, plan)
                return
            if path == "/api/live/readiness":
                try:
                    self._send_json(200, live_readiness_check())
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                return
            if path == "/api/scan/status":
                self._send_json(200, scan_status())
                return
            if path == "/api/super-brainiac/status":
                from raydium_lp1.super_brainiac.possibilities import load_brainiac_config, report_path

                cfg, _ = load_brainiac_config(paths.settings_path)
                rpath = report_path(cfg)
                if not rpath.is_file():
                    self._send_json(
                        200,
                        {"ok": True, "empty": True, "report_path": str(rpath), "message": "No scan yet"},
                    )
                    return
                try:
                    data = json.loads(rpath.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, data)
                return
            if path == "/api/super-brainiac/docs":
                from raydium_lp1.super_brainiac.possibilities import LOGIC_DOCS, load_brainiac_config
                from raydium_lp1.super_brainiac.create_pool_analysis import analyze_create_pool_feasibility

                bcfg, _ = load_brainiac_config(paths.settings_path)
                self._send_json(
                    200,
                    {
                        "logic": LOGIC_DOCS,
                        "create_pool": analyze_create_pool_feasibility(),
                        "config": {
                            "target_apr_pct": bcfg.target_apr_pct,
                            "deposit_usd": bcfg.deposit_usd,
                            "min_liquidity_usd": bcfg.min_liquidity_usd,
                            "require_pay_alt_pair_only": bcfg.require_pay_alt_pair_only,
                        },
                    },
                )
                return
            if path == "/api/scan_console":
                if WEB_SCAN_CONSOLE_LOG.is_file():
                    try:
                        raw = WEB_SCAN_CONSOLE_LOG.read_bytes()
                    except OSError as exc:
                        self._send(500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                        return
                    self._send(200, raw, "text/plain; charset=utf-8")
                    return
                self._send(200, b"(scan console log not found)\n", "text/plain; charset=utf-8")
                return
            if path == "/health":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "raydium-lp1-dashboard",
                        "port": self.server.server_address[1],
                        "api_version": API_VERSION,
                        "api_features": list(API_FEATURES),
                    },
                )
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = up.urlparse(self.path).path.rstrip("/") or "/"
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            if path == "/api/scan/run":
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError:
                    body = {}
                wr = bool(body.get("write_rejections", True))
                result = start_dashboard_scan(write_rejections=wr)
                code = 200 if result.get("ok") else 409
                self._send_json(code, result)
                return
            if path == "/api/tune/apply":
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": f"invalid JSON: {exc}"})
                    return
                ids = body.get("ids") or body.get("item_ids") or []
                if body.get("apply_all"):
                    plan = build_tune_plan(
                        latest_path=paths.dashboard_path.parent / "latest.json",
                        settings_path=paths.settings_path,
                    )
                    ids = [
                        str(it["id"])
                        for it in (plan.get("items") or [])
                        if isinstance(it, dict) and it.get("settings_patch")
                    ]
                if not isinstance(ids, list):
                    self._send_json(400, {"error": "ids must be a list"})
                    return
                try:
                    result = apply_tune_items(
                        paths.settings_path,
                        [str(x) for x in ids],
                        latest_path=paths.dashboard_path.parent / "latest.json",
                    )
                except (OSError, ValueError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, result)
                return
            if path == "/api/super-brainiac/scan":
                try:
                    body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": f"invalid JSON: {exc}"})
                    return
                try:
                    from raydium_lp1.super_brainiac.possibilities import (
                        load_brainiac_config,
                        scan_brainiac_universe,
                        write_brainiac_report,
                    )

                    cfg, scanner = load_brainiac_config(paths.settings_path)
                    dep_raw = body.get("deposit_usd") or body.get("input_amount_usd")
                    if dep_raw not in (None, ""):
                        dep_usd = float(dep_raw)
                        if dep_usd > 0:
                            cfg = replace(cfg, deposit_usd=dep_usd)
                    report = scan_brainiac_universe(cfg=cfg, scanner=scanner)
                    rpath = write_brainiac_report(report, cfg)
                    self._send_json(200, {"ok": True, "report_path": str(rpath), "report": report})
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                return
            if path == "/api/super-brainiac/run-once":
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": f"invalid JSON: {exc}"})
                    return
                if str(body.get("confirm", "")).upper() != "LIVE":
                    self._send_json(400, {"error": "POST confirm=LIVE required"})
                    return
                try:
                    from raydium_lp1.super_brainiac.possibilities import run_brainiac_cycle

                    dep_raw = body.get("deposit_usd") or body.get("input_amount_usd")
                    dep_usd = float(dep_raw) if dep_raw not in (None, "") else None
                    result = run_brainiac_cycle(
                        execute_live=True,
                        settings_path=paths.settings_path,
                        deposit_usd=dep_usd,
                    )
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200 if result.get("ok") else 502, result)
                return
            if path == "/api/lp/harvest-fees":
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": f"invalid JSON: {exc}"})
                    return
                if str(body.get("confirm", "")).upper() != "LIVE":
                    self._send_json(400, {"error": "POST confirm=LIVE required"})
                    return
                try:
                    settings = load_settings_json(paths.settings_path)
                    from raydium_lp1.lp_harvest_fees import (
                        harvest_all_open_position_fees,
                        harvest_clmm_position_fees,
                    )

                    nft = str(body.get("position_nft_mint") or "").strip()
                    pool_id = str(body.get("pool_id") or "").strip() or None
                    if nft:
                        result = harvest_clmm_position_fees(
                            nft,
                            config=settings,
                            fee_guard_settings=settings,
                        )
                    else:
                        result = harvest_all_open_position_fees(
                            config=settings,
                            pool_id=pool_id,
                            fee_guard_settings=settings,
                        )
                except ModeBlockedError as exc:
                    self._send_json(403, {"error": str(exc)})
                    return
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200 if result.get("ok") else 502, result)
                return
            if path == "/api/live/open":
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": f"invalid JSON: {exc}"})
                    return
                if str(body.get("confirm", "")).upper() != "LIVE":
                    self._send_json(400, {"error": "POST confirm=LIVE required"})
                    return
                try:
                    dep_raw = body.get("deposit_usd") or body.get("input_amount_usd")
                    dep_usd = float(dep_raw) if dep_raw not in (None, "") else None
                    sol_raw = body.get("input_amount_sol")
                    settings = load_settings_json(paths.settings_path)
                    sol_price = float(
                        body.get("sol_price_usd")
                        or settings.get("lp_pay_funding_sol_price_usd")
                        or 180
                    ) or 180.0
                    amount_sol = (
                        float(sol_raw)
                        if sol_raw not in (None, "")
                        else (dep_usd / sol_price if dep_usd else None)
                    )
                    result = open_clmm_candidate(
                        pool_id=str(body.get("pool_id") or "") or None,
                        input_amount_sol=amount_sol,
                        input_amount_usd=dep_usd,
                        sol_price_usd=sol_price,
                    )
                except (FileNotFoundError, ValueError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                except ModeBlockedError as exc:
                    self._send_json(403, {"error": str(exc)})
                    return
                self._send_json(200 if result.get("ok") else 502, result)
                return
            if path == "/api/mode":
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": f"invalid JSON: {exc}"})
                    return
                try:
                    result = mode_toggle.set_mode(
                        str(body.get("mode", "")),
                        confirm=body.get("confirm"),
                        source="dashboard",
                    )
                except ModeChangeError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                from raydium_lp1.doctor_advisor import _wallet_runtime

                self._send_json(200, {**result, "wallet": _wallet_runtime()})
                return
            if path not in ("/api/settings",):
                self._send_json(404, {"error": "not found"})
                return
            try:
                patch = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"invalid JSON: {exc}"})
                return
            try:
                patch = _normalize_settings_mode_patch(patch)
                patch, mode_result = _apply_settings_mode_change(
                    paths.settings_path, patch, source="dashboard_settings"
                )
                if patch:
                    merge_known_settings_patch(paths.settings_path, patch)
            except ModeChangeError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except (OSError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            from raydium_lp1 import mode_toggle
            from raydium_lp1.doctor_advisor import _wallet_runtime

            self._send_json(
                200,
                {
                    "ok": True,
                    "path": str(paths.settings_path.resolve()),
                    **mode_toggle.status(),
                    "wallet": _wallet_runtime(),
                },
            )

    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    base = f"http://{args.host}:{args.port}"
    print(f"Raydium-LP1 dashboard {base}/", flush=True)
    print(f"  positions view: {base}/positions.html", flush=True)
    print(f"  project page:   {base}/index.html", flush=True)
    print(f"  dashboard JS:   {DASHBOARD_CLIENT_JS.resolve()}", flush=True)
    print(f"  settings file:  {paths.settings_path.resolve()}", flush=True)
    print(f"  API v{API_VERSION}: GET /api/scan/status  POST /api/scan/run", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
















