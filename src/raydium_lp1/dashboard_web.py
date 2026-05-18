"""Local funnel + settings dashboard (loopback-only HTTP).

``GET /`` serves a single-page UI. ``GET /api/dashboard`` and ``GET /api/settings`` return JSON.
``POST /api/settings`` merges an object into ``config/settings.json`` (scanner-known keys only).

Windows Terminal (PowerShell), two windows from repo root::

    .\\scripts\\run_scan_dashboard.ps1
    .\\scripts\\run_dashboard_web.ps1

Then open http://127.0.0.1:8844/
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from raydium_lp1.dashboard import (
    DEFAULT_DASHBOARD_PATH,
    SCAN_HEARTBEAT_PATH,
    SETTINGS_SAVE_ACK_PATH,
    write_settings_save_ack,
)
from raydium_lp1.dashboard_web_assets import _CLIENT_JS, _CSS_HTML
from raydium_lp1.settings_io import load_settings_json, merge_known_settings_patch
from raydium_lp1.settings_optimizer import (
    DEFAULT_STATE_PATH as OPTIMIZER_STATE_PATH,
    SETTINGS_CATALOG,
    analyze,
    apply_recommendations,
    run_cycle,
    set_auto_apply,
)
from raydium_lp1.strategies import ALLOWED_STRATEGIES

DEFAULT_SETTINGS_PATH = Path("config/settings.json")


def _iso_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


_FORM_SECTIONS: list[dict[str, Any]] = [
    {
        "title": "Liquidity gates",
        "fields": [
            {"key": "min_apr", "label": "Min APR %", "type": "number", "step": "any"},
            {"key": "min_liquidity_usd", "label": "Min TVL (USD)", "type": "number", "step": "any"},
            {"key": "min_volume_24h_usd", "label": "Min Vol 24h (USD)", "type": "number", "step": "any"},
            {"key": "hard_exit_min_tvl_usd", "label": "Hard reject if TVL < (USD)", "type": "number", "step": "any"},
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
            {"key": "sort_candidates_by_momentum", "label": "Sort candidates by momentum", "type": "checkbox"},
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
            {"key": "route_sources_json", "label": "route_sources (JSON array)", "type": "json_text"},
            {"key": "write_rejections", "label": "Write rejections CSV", "type": "checkbox"},
            {"key": "rejections_csv_path", "label": "Rejections CSV path", "type": "text"},
        ],
    },
    {
        "title": "Wallet and emergency",
        "fields": [
            {"key": "position_size_sol", "label": "Position SOL", "type": "number", "step": "any"},
            {"key": "reserve_sol", "label": "Reserve SOL", "type": "number", "step": "any"},
            {"key": "emergency_close_enabled", "label": "Emergency close", "type": "checkbox"},
            {"key": "emergency_max_slippage_pct", "label": "Emergency max slip (0-1 frac)", "type": "number", "step": "any"},
            {"key": "emergency_base_symbol", "label": "Emergency base symbol", "type": "text"},
            {"key": "emergency_alerts_path", "label": "Alerts path", "type": "text"},
            {"key": "track_liquidity_health", "label": "Track liquidity health", "type": "checkbox"},
            {"key": "liquidity_history_path", "label": "Liquidity history path", "type": "text"},
        ],
    },
    {
        "title": "LP paper planning",
        "fields": [
            {"key": "lp_planning_enabled", "label": "LP planning", "type": "checkbox"},
            {"key": "lp_range_mode", "label": "Range mode", "type": "text"},
            {"key": "lp_default_range_width_pct", "label": "Default band %", "type": "number", "step": "any"},
            {"key": "lp_range_width_candidates_json", "label": "Band width candidates JSON", "type": "json_text"},
            {"key": "lp_skew_use_momentum", "label": "Skew bands via momentum", "type": "checkbox"},
            {"key": "lp_full_range_parallel", "label": "Parallel full-range paper leg", "type": "checkbox"},
            {"key": "lp_full_range_budget_fraction", "label": "Full-range budget frac", "type": "number", "step": "any"},
            {"key": "lp_main_budget_fraction", "label": "Main budget frac", "type": "number", "step": "any"},
            {"key": "lp_max_positions_per_mint", "label": "Max LP positions/mint", "type": "number"},
        ],
    },
    {
        "title": "Network metadata",
        "fields": [
            {"key": "strategy", "label": "strategy", "type": "select", "options": list(ALLOWED_STRATEGIES)},
            {"key": "network", "label": "network", "type": "text"},
            {"key": "risk_profile", "label": "risk_profile", "type": "text"},
            {"key": "dry_run", "label": "Dry run only", "type": "checkbox"},
            {"key": "raydium_api_base", "label": "Raydium API base", "type": "text"},
            {"key": "solana_rpc_urls_lines", "label": "RPC URLs (one per line)", "type": "lines"},
            {"key": "allowed_quote_symbols_csv", "label": "Allowed quotes CSV", "type": "csv"},
            {"key": "blocked_token_symbols_csv", "label": "Blocked symbols CSV", "type": "csv"},
            {"key": "blocked_mints_lines", "label": "Blocked mints lines", "type": "lines"},
            {"key": "dashboard_path", "label": "Dashboard JSON path", "type": "text"},
            {"key": "scan_loop", "label": "scan_loop (prefer CLI)", "type": "checkbox"},
            {"key": "scan_loop_interval_seconds", "label": "Loop interval hint (s)", "type": "number"},
            {"key": "spawn_verdict_watcher", "label": "Spawn verdict watcher", "type": "checkbox"},
            {"key": "scan_tune_mode", "label": "Tune mode (TVL sort, no routes)", "type": "checkbox"},
            {"key": "scan_hyper_apr_mode", "label": "Hyper-APR mode (APR-ranked shortlist)", "type": "checkbox"},
            {"key": "sort_candidates_by_apr", "label": "Sort shortlist by APR", "type": "checkbox"},
            {
                "key": "settings_optimizer_auto_apply",
                "label": "Auto-tune settings (optimizer)",
                "type": "checkbox",
            },
        ],
    },
]



@dataclass(frozen=True)
class WebPaths:
    dashboard_path: Path
    settings_path: Path


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


_DRIFT_COMPARE_KEYS = (
    "min_apr",
    "min_liquidity_usd",
    "pool_sort_field",
    "pages",
    "require_sell_route",
)


def _snapshot_settings_from_dashboard(dash_blob: dict[str, Any] | None) -> dict[str, Any]:
    if not dash_blob:
        return {}
    snap_settings = dash_blob.get("settings") if isinstance(dash_blob.get("settings"), dict) else {}
    return {
        "generated_at": dash_blob.get("generated_at"),
        "min_apr": snap_settings.get("min_apr"),
        "min_liquidity_usd": snap_settings.get("min_liquidity_usd"),
        "pool_sort_field": snap_settings.get("pool_sort_field"),
        "pages": snap_settings.get("pages"),
        "require_sell_route": snap_settings.get("require_sell_route"),
    }


def _settings_on_disk_summary(settings_path: Path) -> dict[str, Any]:
    try:
        raw = load_settings_json(settings_path)
    except (OSError, ValueError):
        return {}
    return {key: raw.get(key) for key in _DRIFT_COMPARE_KEYS}


def _settings_drift_keys(snap: dict[str, Any], on_disk: dict[str, Any]) -> list[str]:
    if not snap or not on_disk:
        return []
    return [key for key in _DRIFT_COMPARE_KEYS if snap.get(key) != on_disk.get(key)]


def _settings_save_warnings(on_disk: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    min_apr = on_disk.get("min_apr")
    if isinstance(min_apr, (int, float)) and min_apr > 50:
        warnings.append(
            f"min_apr={min_apr:g} is very high — expect mass apr_below_threshold rejects until you lower it."
        )
    if on_disk.get("require_sell_route") is True:
        warnings.append(
            "require_sell_route=true — scans probe Jupiter/Raydium per pool and can take a long time; "
            "uncheck for tune-style scans or use scripts/run_tune_scan.ps1."
        )
    pool_sort = str(on_disk.get("pool_sort_field") or "").strip().lower()
    if not pool_sort or pool_sort in {"apr", "apr24h"}:
        warnings.append(
            "pool_sort_field is empty or APR-sorted — page 1 is often dust TVL; set liquidity for discovery."
        )
    return warnings


def _status_payload(paths: WebPaths) -> dict[str, Any]:
    heartbeat = _read_json_file(SCAN_HEARTBEAT_PATH)
    save_ack = _read_json_file(SETTINGS_SAVE_ACK_PATH)
    dash_mtime = _iso_mtime(paths.dashboard_path)
    settings_mtime = _iso_mtime(paths.settings_path)
    phase = (heartbeat or {}).get("phase")
    scanning = phase in {"scan_start", "page_fetch", "page_failed"}
    dash_blob = _read_json_file(paths.dashboard_path)
    snap = _snapshot_settings_from_dashboard(dash_blob)
    on_disk = _settings_on_disk_summary(paths.settings_path)
    drift_keys = _settings_drift_keys(snap, on_disk)
    return {
        "settings_path": str(paths.settings_path.resolve()),
        "settings_mtime": settings_mtime,
        "dashboard_path": str(paths.dashboard_path.resolve()),
        "dashboard_mtime": dash_mtime,
        "heartbeat_path": str(SCAN_HEARTBEAT_PATH.resolve()),
        "heartbeat": heartbeat,
        "settings_save_ack": save_ack,
        "scanner_scanning": scanning,
        "dashboard_scan_settings": snap,
        "settings_on_disk": on_disk,
        "settings_drift_keys": drift_keys,
        "settings_apply": {
            "how": "POST /api/settings merges into settings.json (known keys only).",
            "scanner": "Scanner tab must use run_scan_dashboard.ps1 (--reload-config-each-scan).",
            "when": "Funnel numbers update only after a full scan finishes (dashboard.json).",
        },
    }


def _embed_json_in_html_script(payload: dict[str, Any]) -> str:
    """Serialize JSON safe inside a ``<script>`` tag (no ``</script>`` breakout)."""

    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e")


def _optimizer_api(paths: WebPaths, *, force_apply: bool = False) -> dict[str, Any]:
    snap = run_cycle(settings_path=paths.settings_path, dashboard_path=paths.dashboard_path)
    if force_apply:
        apply_recommendations(snap, paths.settings_path, force=True)
    state = snap.to_dict()
    try:
        current = load_settings_json(paths.settings_path)
    except (OSError, ValueError):
        current = {}
    state["current_settings"] = {k: current.get(k) for k in snap.recommended_patch}
    state["settings_catalog"] = SETTINGS_CATALOG
    return state


def _page() -> bytes:
    boot_payload = {"form_sections": _FORM_SECTIONS, "settings_catalog": SETTINGS_CATALOG}
    html = (
        _CSS_HTML.replace(
            "BOOT_JSON",
            _embed_json_in_html_script(boot_payload),
        ).replace(
            "CLIENT_JS_HERE",
            _CLIENT_JS,
        )
    )
    return html.encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    import urllib.parse as up  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Raydium-LP1 local dashboard (127.0.0.1 only).")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default loopback).")
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
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, obj: Any) -> None:
            raw = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            self._send(code, raw, "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            path = up.urlparse(self.path).path
            if path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(blob["page"])))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(blob["page"])
                return
            if path == "/api/dashboard":
                dpath = paths.dashboard_path
                if not dpath.exists():
                    self._send_json(
                        404,
                        {"error": f"Dashboard not found: {dpath} (run scanner with --dashboard)"},
                    )
                    return
                try:
                    data = json.loads(dpath.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, data)
                return
            if path == "/api/settings":
                sp = paths.settings_path
                try:
                    data = load_settings_json(sp)
                except (OSError, ValueError) as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, data)
                return
            if path == "/api/status":
                self._send_json(200, _status_payload(paths))
                return
            if path == "/api/optimizer":
                try:
                    self._send_json(200, _optimizer_api(paths))
                except OSError as exc:
                    self._send_json(500, {"error": str(exc)})
                return
            if path == "/api/settings/help":
                self._send_json(200, {"catalog": SETTINGS_CATALOG})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = up.urlparse(self.path).path
            if path == "/api/optimizer/toggle":
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                enabled = bool(body.get("enabled"))
                try:
                    set_auto_apply(enabled, paths.settings_path)
                except (OSError, ValueError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                snap = run_cycle(settings_path=paths.settings_path, dashboard_path=paths.dashboard_path)
                if enabled:
                    apply_recommendations(snap, paths.settings_path, force=True)
                self._send_json(200, snap.to_dict())
                return
            if path == "/api/optimizer/apply":
                try:
                    snap = run_cycle(settings_path=paths.settings_path, dashboard_path=paths.dashboard_path)
                    applied = apply_recommendations(snap, paths.settings_path, force=True)
                    self._send_json(200, {"ok": True, "applied": applied, "snapshot": snap.to_dict()})
                except (OSError, ValueError) as exc:
                    self._send_json(400, {"error": str(exc)})
                return
            if path != "/api/settings":
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                patch = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"invalid JSON: {exc}"})
                return
            try:
                merge_known_settings_patch(paths.settings_path, patch)
            except (OSError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            keys_patched = sorted(str(k) for k in patch.keys())
            write_settings_save_ack(keys_patched=keys_patched, settings_path=paths.settings_path)
            on_disk = _settings_on_disk_summary(paths.settings_path)
            dash_blob = _read_json_file(paths.dashboard_path)
            snap = _snapshot_settings_from_dashboard(dash_blob)
            drift_keys = _settings_drift_keys(snap, on_disk)
            self._send_json(
                200,
                {
                    "ok": True,
                    "path": str(paths.settings_path.resolve()),
                    "settings_mtime": _iso_mtime(paths.settings_path),
                    "keys_patched": keys_patched,
                    "settings_drift_keys": drift_keys,
                    "dashboard_scan_settings": snap,
                    "settings_on_disk": on_disk,
                    "warnings": _settings_save_warnings(on_disk),
                    "scanner_note": "Next scan loop reloads settings when run_scan_dashboard.ps1 is used.",
                },
            )

    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Raydium-LP1 dashboard http://{args.host}:{args.port}/", flush=True)
    print(f"  dashboard JSON: {paths.dashboard_path}", flush=True)
    print(f"  settings file: {paths.settings_path}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
