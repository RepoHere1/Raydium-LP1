"""Local funnel + settings dashboard (loopback-only HTTP).

``GET /`` serves HTML assembled from ``web/dashboard_shell.html`` plus the
boot JSON; ``GET /dashboard_client.js`` serves the browser bundle from
``web/dashboard_client.js`` (kept outside this module so merges cannot leave
Git conflict markers inside Python string literals).

``GET /api/dashboard`` and ``GET /api/settings`` return JSON.
``GET /api/dashboard/events`` streams **Server-Sent Events**: whenever the dashboard JSON file
changes (mtime/size), the server emits ``tick`` so the browser can refetch immediately (no
extra Raydium traffic from the UI — the scanner still writes the file).
``POST /api/settings`` merges an object into ``config/settings.json`` (scanner-known keys only).

Use with::

    python -m raydium_lp1.dashboard_web

and run the scanner with ``--dashboard --loop --reload-config-each-scan`` while you tune gates,
or ``python -m raydium_lp1.web_stack`` so the scanner child and dashboard share one process.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from raydium_lp1.dashboard import DEFAULT_DASHBOARD_PATH
from raydium_lp1.dashboard_field_help import attach_field_help, attach_section_help
from raydium_lp1.settings_io import load_settings_json, merge_known_settings_patch
from raydium_lp1.strategies import ALLOWED_STRATEGIES

DEFAULT_SETTINGS_PATH = Path("config/settings.json")
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_STATIC_DIR = REPO_ROOT / "web"
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


def _serve_repo_static(url_path: str) -> tuple[bytes, str] | None:
    """Serve whitelisted static files from ``web/`` and repo ``styles.css``."""

    files: dict[str, Path] = {
        "/positions.html": WEB_STATIC_DIR / "positions.html",
        "/index.html": WEB_STATIC_DIR / "index.html",
        "/styles.css": REPO_ROOT / "styles.css",
        "/dashboard_client.js": DASHBOARD_CLIENT_JS,
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
        ],
    },
]

attach_field_help(_FORM_SECTIONS)
attach_section_help(_FORM_SECTIONS)


@dataclass(frozen=True)
class WebPaths:
    dashboard_path: Path
    settings_path: Path


def _dashboard_signature(dpath: Path) -> tuple[int, int] | None:
    """Return ``(mtime_ns, size)`` for a regular file, or ``None`` if missing/unreadable."""

    try:
        st = dpath.stat()
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def _stream_dashboard_sse(wfile: Any, dpath: Path) -> None:
    """Write SSE until the client disconnects; emit ``tick`` when ``dpath`` changes."""

    poll_s = 0.75
    heartbeat_s = 15.0
    last_sig = _dashboard_signature(dpath)
    last_beat = time.monotonic()
    try:
        while True:
            time.sleep(poll_s)
            now = time.monotonic()
            sig = _dashboard_signature(dpath)
            if sig != last_sig:
                last_sig = sig
                payload = {
                    "mtime_ns": sig[0] if sig else None,
                    "size": sig[1] if sig else None,
                    "exists": sig is not None,
                }
                line = (
                    "event: tick\ndata: "
                    + json.dumps(payload, separators=(",", ":"))
                    + "\n\n"
                )
                wfile.write(line.encode("utf-8"))
                wfile.flush()
            if now - last_beat >= heartbeat_s:
                wfile.write(b": ping\n\n")
                wfile.flush()
                last_beat = now
    except (BrokenPipeError, ConnectionResetError, TimeoutError):
        return
    except OSError as exc:
        if getattr(exc, "errno", None) in (104, 32, 10053):  # ECONNRESET / EPIPE-ish
            return
        raise


def _page() -> bytes:
    """Assemble ``GET /`` HTML from ``web/dashboard_shell.html`` + boot JSON.

    The large client script lives in ``web/dashboard_client.js`` so routine Git
    merges on ``dashboard_web.py`` cannot corrupt the browser bundle with
    conflict markers inside Python string literals.
    """

    if not DASHBOARD_SHELL_HTML.is_file():
        raise RuntimeError(
            f"Dashboard UI shell missing: {DASHBOARD_SHELL_HTML}. "
            "Restore web/dashboard_shell.html from the repository."
        )
    shell = DASHBOARD_SHELL_HTML.read_text(encoding="utf-8")
    if "BOOT_JSON" not in shell:
        raise RuntimeError(f"{DASHBOARD_SHELL_HTML} must contain the BOOT_JSON placeholder")
    boot_payload = {"form_sections": _FORM_SECTIONS}
    html = shell.replace(
        "BOOT_JSON",
        json.dumps(boot_payload, separators=(",", ":")),
    )
    raw = html.encode("utf-8")
    if b"<<<<<<<" in raw or b">>>>>>>" in raw:
        raise RuntimeError(
            "dashboard shell contains git merge conflict markers — fix web/dashboard_shell.html"
        )
    if DASHBOARD_CLIENT_JS.is_file():
        js_bytes = DASHBOARD_CLIENT_JS.read_bytes()
        if b"<<<<<<<" in js_bytes or b">>>>>>>" in js_bytes:
            raise RuntimeError(
                "dashboard_client.js contains git merge conflict markers — fix web/dashboard_client.js"
            )
    return raw


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
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")
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
            if path == "/api/dashboard/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                try:
                    self.wfile.write(b": stream open\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                _stream_dashboard_sse(self.wfile, paths.dashboard_path)
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
            if path == "/api/scan_console":
                if WEB_SCAN_CONSOLE_LOG.is_file():
                    try:
                        raw = WEB_SCAN_CONSOLE_LOG.read_bytes()
                    except OSError as exc:
                        self._send(500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                        return
                    self._send(200, raw, "text/plain; charset=utf-8")
                    return
                msg = (
                    "(No scan console log here. It is written when you run "
                    "`python -m raydium_lp1.web_stack` with the scanner child, which tees stdout to "
                    f"{WEB_SCAN_CONSOLE_LOG.name}.)\n"
                )
                self._send(200, msg.encode("utf-8"), "text/plain; charset=utf-8")
                return
            if path == "/health":
                self._send_json(200, {"ok": True, "service": "raydium-lp1-dashboard", "port": self.server.server_address[1]})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = up.urlparse(self.path).path
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")
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
            self._send_json(200, {"ok": True, "path": str(paths.settings_path.resolve())})

    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    base = f"http://{args.host}:{args.port}"
    print(f"Raydium-LP1 dashboard {base}/", flush=True)
    print(f"  SSE push:       {base}/api/dashboard/events (refetch when dashboard JSON changes)", flush=True)
    print(f"  positions view: {base}/positions.html", flush=True)
    print(f"  project page:   {base}/index.html", flush=True)
    print(f"  dashboard JS:   {DASHBOARD_CLIENT_JS.resolve()}", flush=True)
    print(f"  settings file:  {paths.settings_path.resolve()}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
