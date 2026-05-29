"""Autonomous heal: scanner JSON ↔ dashboard ↔ HTML/JS stay in sync."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from raydium_lp1.doctor_data_flow import (
    DEFAULT_DASHBOARD,
    DEFAULT_LATEST,
    WEB,
    DataFlowCheck,
    run_data_flow_checks,
)

REPO = Path(__file__).resolve().parent.parent.parent
SETTINGS = REPO / "config" / "settings.json"

# Checks the doctor can fix without user action.
_HEALABLE = frozenset(
    {
        "dashboard_json",
        "dashboard_vs_latest",
        "api_vs_dashboard_file",
        "html_cand_panel",
        "js_candidate_renderer",
        "js_candidate_cap",
        "mom_table_sort",
        "positions_candidates",
        "latest_candidate_count",
    }
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".doctor_tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def heal_refresh_dashboard_from_latest(
    *,
    latest_path: Path = DEFAULT_LATEST,
    dashboard_path: Path = DEFAULT_DASHBOARD,
    settings_path: Path = SETTINGS,
) -> bool:
    """Rebuild reports/dashboard.json from reports/latest.json."""

    if not latest_path.is_file():
        return False
    try:
        report = json.loads(latest_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            return False
    except (OSError, json.JSONDecodeError):
        return False

    from raydium_lp1.dashboard import build_dashboard, write_dashboard
    from raydium_lp1.scanner import ScannerConfig, check_rpc_urls, load_dotenv

    load_dotenv()
    config = ScannerConfig.from_file(settings_path)
    rpc_health = check_rpc_urls(config.solana_rpc_urls)
    data = build_dashboard(
        config=config,
        report=report,
        rpc_health=rpc_health,
        alerts_path=Path(config.emergency_alerts_path),
    )
    write_dashboard(data, dashboard_path)
    return True


def _patch_file(path: Path, replacements: list[tuple[str, str]]) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    orig = text
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
    if text == orig:
        return False
    _write_text(path, text)
    return True


def heal_web_dashboard_js() -> list[str]:
    """Apply known-good JS patterns for candidate/MoM tables."""

    fixed: list[str] = []
    dc = WEB / "dashboard_client.js"
    patches: list[tuple[str, str]] = [
        (
            "function renderMomentumTable(el, rows){\n    rows=sortPoolsByAprDesc(rows||[]);",
            "function renderMomentumTable(el, rows){\n    rows=sortPoolsByMomentumDesc(rows||[]);",
        ),
        (
            "if(sc!=null&&Number(sc)>=90) return true;",
            "if(sc!=null&&Number(sc)>=minScore&&poolApr(p)>=minApr) return true;",
        ),
    ]
    if _patch_file(dc, patches):
        fixed.append("dashboard_client.js")

    # Ensure momentum sort helper exists
    text = dc.read_text(encoding="utf-8", errors="replace") if dc.is_file() else ""
    if "function sortPoolsByMomentumDesc" not in text and "function sortPoolsByAprDesc" in text:
        insert_after = "function sortPoolsByAprDesc(pools){"
        idx = text.find(insert_after)
        if idx >= 0:
            end = text.find("\n  }", idx)
            if end > idx:
                helper = (
                    "\n\n  function sortPoolsByMomentumDesc(pools){\n"
                    "    return pools.slice().sort(function(a,b){\n"
                    "      var ma=a.momentum||{}, mb=b.momentum||{};\n"
                    "      var sa=Number(ma.combined_score!=null?ma.combined_score:ma.score)||0;\n"
                    "      var sb=Number(mb.combined_score!=null?mb.combined_score:mb.score)||0;\n"
                    "      return sb-sa;\n"
                    "    });\n"
                    "  }"
                )
                text = text[: end + 4] + helper + text[end + 4 :]
                _write_text(dc, text)
                if "dashboard_client.js" not in fixed:
                    fixed.append("dashboard_client.js")

    pc = WEB / "positions_client.js"
    if pc.is_file():
        pt = pc.read_text(encoding="utf-8", errors="replace")
        if "function sortPoolsForPick" not in pt and "sortByApr((d.last_scan" in pt:
            block = (
                "  function sortPoolsForPick(pools, d) {\n"
                "    var mode = String(((d && d.settings) || {}).lp_selection_mode || 'apr').toLowerCase();\n"
                "    if (mode === 'momentum') {\n"
                "      return pools.slice().sort(function (a, b) {\n"
                "        var ma = a.momentum || {}, mb = b.momentum || {};\n"
                "        var sa = Number(ma.combined_score != null ? ma.combined_score : ma.score) || 0;\n"
                "        var sb = Number(mb.combined_score != null ? mb.combined_score : mb.score) || 0;\n"
                "        return sb - sa;\n"
                "      });\n"
                "    }\n"
                "    return sortByApr(pools);\n"
                "  }\n"
            )
            marker = "  function sortByApr(pools) {"
            if marker in pt:
                pt = pt.replace(marker, block + marker)
                _write_text(pc, pt)
                fixed.append("positions_client.js")

    return fixed


def heal_html_cand_panel() -> bool:
    """Ensure dashboard_shell.html exposes #cand candidate table mount."""

    path = WEB / "dashboard_shell.html"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if 'id="cand"' in text:
        return False
    snippet = (
        '<section class="panel"><h2>Candidate pools '
        '<span class="pill pill-sim">scanner shortlist</span></h2>'
        '<div id="cand" class="bd"></div></section>\n'
    )
    if 'id="mom"' in text:
        text = text.replace('<section class="panel"><h2>Momentum HOT', snippet + '<section class="panel"><h2>Momentum HOT', 1)
    else:
        text = text + "\n" + snippet
    _write_text(path, text)
    return True


def heal_latest_candidate_count(latest_path: Path = DEFAULT_LATEST) -> bool:
    """Fix candidate_count when it disagrees with len(candidates)."""

    if not latest_path.is_file():
        return False
    try:
        raw = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    cands = raw.get("candidates") or []
    if not isinstance(cands, list):
        return False
    n = len(cands)
    if int(raw.get("candidate_count") or 0) == n:
        return False
    raw["candidate_count"] = n
    raw["candidate_count_pre_capacity"] = n
    _write_text(latest_path, json.dumps(raw, indent=2, sort_keys=False) + "\n")
    return True


def heal_strip_merge_markers_web() -> list[str]:
    """Remove git conflict markers from web/*.js|html if present."""

    fixed: list[str] = []
    for path in WEB.glob("*"):
        if path.suffix not in (".js", ".html"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "<<<<<<<" not in text and ">>>>>>>" not in text:
            continue
        cleaned = re.sub(r"^<<<<<<<[^\n]*\n.*?^=======\n.*?^>>>>>>>[^\n]*\n?", "", text, flags=re.M | re.S)
        if cleaned != text:
            _write_text(path, cleaned)
            fixed.append(path.name)
    return fixed


def run_data_flow_heal_pass(*, dashboard_port: int) -> list[str]:
    """One heal pass; returns list of actions taken."""

    actions: list[str] = []
    actions.extend(heal_strip_merge_markers_web())
    if heal_latest_candidate_count():
        actions.append("fixed latest.json candidate_count")
    if heal_refresh_dashboard_from_latest():
        actions.append("rebuilt dashboard.json from latest.json")
    js = heal_web_dashboard_js()
    actions.extend(f"patched {x}" for x in js)
    if heal_html_cand_panel():
        actions.append("inserted #cand panel in dashboard_shell.html")
    return actions


def heal_data_flow_integrity(
    *,
    heal: bool,
    dashboard_port: int,
    max_passes: int = 3,
) -> list[DataFlowCheck]:
    """Check → auto-heal → re-check until green or pass limit."""

    checks = run_data_flow_checks(dashboard_port=dashboard_port)
    if not heal:
        return checks

    for _ in range(max_passes):
        failed_names = {c.name for c in checks if not c.ok and c.name in _HEALABLE}
        if not failed_names:
            break
        actions = run_data_flow_heal_pass(dashboard_port=dashboard_port)
        if not actions:
            break
        new_checks = run_data_flow_checks(dashboard_port=dashboard_port)
        healed_names = failed_names - {c.name for c in new_checks if not c.ok}
        for c in new_checks:
            if c.name in healed_names:
                c.detail = {**c.detail, "healed": True, "heal_actions": list(actions)}
        checks = new_checks

    return checks
