"""Doctor checks: scanner JSON ↔ dashboard API ↔ HTML/JS data flow integrity."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_LATEST = REPO / "reports" / "latest.json"
DEFAULT_DASHBOARD = REPO / "reports" / "dashboard.json"
WEB = REPO / "web"


@dataclass
class DataFlowCheck:
    name: str
    ok: bool
    severity: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _fetch_api_dashboard(port: int, timeout: float = 3.0) -> dict[str, Any] | None:
    url = f"http://127.0.0.1:{port}/api/dashboard"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def _grep_file(path: Path, pattern: str) -> bool:
    if not path.is_file():
        return False
    try:
        return re.search(pattern, path.read_text(encoding="utf-8", errors="replace")) is not None
    except OSError:
        return False


def run_data_flow_checks(
    *,
    latest_path: Path = DEFAULT_LATEST,
    dashboard_path: Path = DEFAULT_DASHBOARD,
    dashboard_port: int | None = None,
) -> list[DataFlowCheck]:
    """Compare scan artifacts, dashboard JSON, live API, and front-end hooks."""

    out: list[DataFlowCheck] = []

    latest = _read_json(latest_path)
    dash_file = _read_json(dashboard_path)

    if latest is None:
        out.append(
            DataFlowCheck(
                "latest_json",
                False,
                "warn",
                f"Missing or invalid {latest_path} — run scanner first.",
            )
        )
    else:
        cands = latest.get("candidates") or []
        n_c = len(cands) if isinstance(cands, list) else 0
        declared = int(latest.get("candidate_count") or 0)
        pre = int(latest.get("candidate_count_pre_capacity") or n_c)
        trunc = int(latest.get("candidates_truncated") or 0)
        if declared != n_c:
            out.append(
                DataFlowCheck(
                    "latest_candidate_count",
                    False,
                    "error",
                    f"latest.json candidate_count={declared} but len(candidates)={n_c}",
                    {"path": str(latest_path)},
                )
            )
        else:
            out.append(
                DataFlowCheck(
                    "latest_candidate_count",
                    True,
                    "info",
                    f"latest.json lists {n_c} candidate(s) (pre-cap {pre}, truncated {trunc}).",
                )
            )
        if int(latest.get("scanned_count") or 0) > 0 and n_c == 0:
            out.append(
                DataFlowCheck(
                    "latest_zero_candidates",
                    False,
                    "warn",
                    "Scanner passed filters for 0 pools — loosen min_apr/TVL/momentum or check rejections CSV.",
                    {"scanned": latest.get("scanned_count"), "rejected": latest.get("rejected_count")},
                )
            )

    if dash_file is None:
        out.append(
            DataFlowCheck(
                "dashboard_json",
                False,
                "warn",
                f"Missing dashboard snapshot {dashboard_path} (scanner writes this on scan).",
            )
        )
    else:
        ls = dash_file.get("last_scan") if isinstance(dash_file.get("last_scan"), dict) else {}
        dc = ls.get("candidates") or []
        n_d = len(dc) if isinstance(dc, list) else 0
        if latest and isinstance(latest.get("candidates"), list):
            n_l = len(latest["candidates"])
            if n_l != n_d:
                out.append(
                    DataFlowCheck(
                        "dashboard_vs_latest",
                        False,
                        "error",
                        f"dashboard.json last_scan has {n_d} candidates but latest.json has {n_l}. "
                        "Re-run scan or hard-refresh dashboard — stale snapshot.",
                        {"dashboard_path": str(dashboard_path), "latest_path": str(latest_path)},
                    )
                )
            else:
                out.append(
                    DataFlowCheck(
                        "dashboard_vs_latest",
                        True,
                        "info",
                        f"dashboard.json and latest.json both expose {n_d} candidate row(s).",
                    )
                )

    port = dashboard_port
    if port is None:
        try:
            from raydium_lp1.raydium_doctor import resolve_dashboard_port

            port = resolve_dashboard_port()
        except Exception:
            port = 8844

    api = _fetch_api_dashboard(port)
    if api is None:
        out.append(
            DataFlowCheck(
                "api_dashboard",
                False,
                "warn",
                f"Could not GET /api/dashboard on :{port} — UI may show stale or empty tables.",
            )
        )
    else:
        ls = api.get("last_scan") if isinstance(api.get("last_scan"), dict) else {}
        n_api = len(ls.get("candidates") or [])
        hot = len(api.get("momentum_hot_top") or [])
        mom_on = bool((api.get("settings") or {}).get("momentum_enabled"))
        out.append(
            DataFlowCheck(
                "api_dashboard",
                True,
                "info",
                f"Live API: {n_api} candidate(s), momentum_hot_top={hot}, momentum_enabled={mom_on}.",
                {"port": port},
            )
        )
        if dash_file and n_api != n_d:
            out.append(
                DataFlowCheck(
                    "api_vs_dashboard_file",
                    False,
                    "error",
                    f"/api/dashboard returns {n_api} candidates but dashboard.json file has {n_d}. "
                    "enrich_dashboard_payload may be out of sync.",
                )
            )
        sel = api.get("lp_selection") if isinstance(api.get("lp_selection"), dict) else {}
        mode = str(sel.get("lp_selection_mode") or (api.get("settings") or {}).get("lp_selection_mode") or "?")
        out.append(
            DataFlowCheck(
                "lp_selection_mode",
                True,
                "info",
                f"LP pick mode for LIVE opens: {mode} ({sel.get('label', '')}).",
                {"top_pool_id": sel.get("top_pool_id")},
            )
        )

    # HTML / JS wiring — static integrity (no row caps in renderCandidateTable)
    html_ok = (WEB / "dashboard_shell.html").is_file() and _grep_file(WEB / "dashboard_shell.html", r'id="cand"')
    js_ok = _grep_file(WEB / "dashboard_client.js", r"function renderCandidateTable")
    js_no_cap = not _grep_file(WEB / "dashboard_client.js", r"pools\.slice\(0,\s*\d+\)")
    pos_ok = _grep_file(WEB / "positions_client.js", r"last_scan\.candidates")

    if not html_ok:
        out.append(
            DataFlowCheck(
                "html_cand_panel",
                False,
                "error",
                "dashboard_shell.html missing #cand candidate panel — UI cannot list pools.",
            )
        )
    if not js_ok:
        out.append(
            DataFlowCheck(
                "js_candidate_renderer",
                False,
                "error",
                "dashboard_client.js missing renderCandidateTable — candidate table broken.",
            )
        )
    elif not js_no_cap:
        out.append(
            DataFlowCheck(
                "js_candidate_cap",
                False,
                "warn",
                "dashboard_client.js may slice candidate rows — verify tbl-scroll shows full list.",
            )
        )
    else:
        out.append(
            DataFlowCheck(
                "js_candidate_renderer",
                True,
                "info",
                "Candidate table renderer present; no hard row cap detected in JS.",
            )
        )

    if not pos_ok:
        out.append(
            DataFlowCheck(
                "positions_candidates",
                False,
                "warn",
                "positions_client.js may not read last_scan.candidates — positions page out of sync.",
            )
        )
    else:
        out.append(
            DataFlowCheck(
                "positions_candidates",
                True,
                "info",
                "Positions page reads last_scan.candidates from /api/dashboard.",
            )
        )

    mom_sort_bug = _grep_file(
        WEB / "dashboard_client.js",
        r"function renderMomentumTable[\s\S]{0,120}sortPoolsByAprDesc",
    )
    mom_sort_ok = _grep_file(WEB / "dashboard_client.js", r"sortPoolsByMomentumDesc\(rows")
    if mom_sort_bug and not mom_sort_ok:
        out.append(
            DataFlowCheck(
                "mom_table_sort",
                False,
                "warn",
                "Momentum HOT table was APR-sorted in JS (should be score-sorted) — fixed in this build if check passes after update.",
            )
        )

    return out


def summarize_data_flow(checks: list[DataFlowCheck]) -> dict[str, Any]:
    bad = [c for c in checks if not c.ok and c.severity in ("error", "critical")]
    return {
        "ok": len(bad) == 0,
        "error_count": len(bad),
        "checks": [
            {
                "name": c.name,
                "ok": c.ok,
                "severity": c.severity,
                "message": c.message,
                "detail": c.detail,
            }
            for c in checks
        ],
    }
