"""
raydium_doctor v1.0 — omnibus self-heal for Raydium-LP1.

Ported from FutureGMGN's smart_doctor.py, adapted for Raydium-LP1's layout.
Covers every failure mode we've seen in this repo:

  - settings_schema.py corruption (literal `r`n PowerShell escapes, 0x08
    backspace bytes, BOM-poisoned UTF-16 from PS `>` redirects)
  - Python AST parse failures across all critical modules
  - JSON state file truncation / wrong type
  - Missing .env keys (SOLANA_RPC_URL, SOLANA_KEYPAIR_PATH)
  - Node bridge missing (raydium_clmm_node/node_modules)
  - Dashboard backend down (auto-restart :8844 in watch mode; see doctor_dashboard_heal.py)
  - Scanner ↔ dashboard.json ↔ /api/dashboard ↔ HTML/JS data flow (auto-heal when heal mode on)

Usage:
  py -3 -m raydium_lp1.raydium_doctor              # one-shot scan
  py -3 -m raydium_lp1.raydium_doctor --watch      # loop every 60s
  py -3 -m raydium_lp1.raydium_doctor --json       # JSON output

Stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

REPO  = Path(__file__).resolve().parent.parent.parent          # Raydium-LP1/
SRC   = REPO / "src" / "raydium_lp1"
LOGS  = REPO / "logs"
ALERTS_PATH = REPO / "alerts.json"
LOG_PATH    = LOGS / "raydium_doctor.log"
SNAPSHOT    = REPO / "doctor_snapshot.json"

# (rel_path, min_lines, sentinel_str)
CRITICAL_PY_FILES = {
    "src/raydium_lp1/settings_schema.py":  (20,  "KNOWN_SETTINGS_KEYS"),
    "src/raydium_lp1/settings_io.py":      (20,  "load_settings_json"),
    "src/raydium_lp1/dashboard_web.py":    (50,  "if __name__"),
    "src/raydium_lp1/web_stack.py":        (30,  "if __name__"),
}

JSON_STATE_FILES = {
    "settings.json":          dict,
    "active_positions.json":  (dict, list),
    "closed_positions.json":  list,
}

ENV_KEYS_REQUIRED = ["SOLANA_RPC_URL", "SOLANA_KEYPAIR_PATH"]

# ---- result type --------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    ok: bool
    severity: str           # "info" | "warn" | "error" | "critical"
    message: str
    healed: bool = False
    detail: dict = field(default_factory=dict)


# ---- IO helpers ---------------------------------------------------------

def now_iso() -> str:
    return datetime.now().isoformat()


def log(msg: str, level: str = "info") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] [raydium_doctor] {msg}"
    print(line, flush=True)
    try:
        LOGS.mkdir(exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def read_json_safe(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def append_alert(severity: str, check: str, msg: str, healed: bool = False) -> None:
    try:
        alerts = read_json_safe(ALERTS_PATH, [])
        if not isinstance(alerts, list):
            alerts = []
        alerts.append({
            "ts":       now_iso(),
            "severity": severity,
            "check":    check,
            "message":  msg,
            "healed":   healed,
        })
        atomic_write_json(ALERTS_PATH, alerts[-200:])
    except Exception:
        pass


# ---- check: Python file integrity ---------------------------------------

_PS_RN_LITERAL = re.compile(r"`r`n")

def check_py_file(rel_path: str, min_lines: int, sentinel: str, *, heal: bool = True) -> CheckResult:
    p = REPO / rel_path
    if not p.exists():
        msg = f"missing: {rel_path}"
        append_alert("critical", f"pyfile:{rel_path}", msg)
        return CheckResult(f"pyfile:{rel_path}", False, "critical", msg)

    try:
        raw_bytes = p.read_bytes()
    except Exception as e:
        msg = f"read failed: {e}"
        append_alert("error", f"pyfile:{rel_path}", msg)
        return CheckResult(f"pyfile:{rel_path}", False, "error", msg)

    detail: dict = {}

    if raw_bytes[:2] in (b"\xff\xfe", b"\xfe\xff"):
        msg = f"UTF-16 BOM in {rel_path} (PowerShell `>` redirect bug)"
        append_alert("error", f"pyfile:{rel_path}", msg)
        return CheckResult(f"pyfile:{rel_path}", False, "error", msg)

    if b"\x08" in raw_bytes:
        count = raw_bytes.count(b"\x08")
        if not heal:
            msg = f"{count} 0x08 byte(s) in {rel_path} (heal disabled)"
            return CheckResult(f"pyfile:{rel_path}", False, "warn", msg, detail={"bytes": count})
        healed_bytes = raw_bytes.replace(b"\x08", b"\\b")
        bak = p.with_suffix(".py.bak.raydoctor-0x08")
        bak.write_bytes(raw_bytes)
        p.write_bytes(healed_bytes)
        msg = f"replaced {count} 0x08 byte(s) with literal \\b in {rel_path}; backup at {bak.name}"
        log(msg, "warn")
        append_alert("warn", f"pyfile:{rel_path}", msg, healed=True)
        return CheckResult(f"pyfile:{rel_path}", True, "warn", msg, healed=True, detail={"bytes": count})

    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        msg = f"non-UTF-8 bytes in {rel_path}: {e}"
        append_alert("error", f"pyfile:{rel_path}", msg)
        return CheckResult(f"pyfile:{rel_path}", False, "error", msg)

    if _PS_RN_LITERAL.search(raw):
        count = len(_PS_RN_LITERAL.findall(raw))
        if not heal:
            msg = f"{count} literal `r`n in {rel_path} (heal disabled)"
            return CheckResult(f"pyfile:{rel_path}", False, "warn", msg)
        healed = _PS_RN_LITERAL.sub("\r\n", raw)
        bak = p.with_suffix(".py.bak.raydoctor-psrn")
        bak.write_text(raw, encoding="utf-8")
        p.write_text(healed, encoding="utf-8")
        msg = f"replaced {count} literal `r`n with real CRLF in {rel_path}; backup at {bak.name}"
        log(msg, "warn")
        append_alert("warn", f"pyfile:{rel_path}", msg, healed=True)
        return CheckResult(f"pyfile:{rel_path}", True, "warn", msg, healed=True, detail={"patches": count})

    line_count = raw.count("\n") + 1
    detail["line_count"] = line_count
    if line_count < min_lines:
        msg = f"truncated: {rel_path} has {line_count} lines (expected >= {min_lines})"
        append_alert("critical", f"pyfile:{rel_path}", msg)
        return CheckResult(f"pyfile:{rel_path}", False, "critical", msg, detail=detail)

    if sentinel and sentinel not in raw:
        msg = f"missing sentinel '{sentinel}' in {rel_path}"
        append_alert("warn", f"pyfile:{rel_path}", msg)
        return CheckResult(f"pyfile:{rel_path}", False, "warn", msg, detail=detail)

    try:
        ast.parse(raw)
    except SyntaxError as e:
        msg = f"AST parse failed in {rel_path} at line {e.lineno}: {e.msg}"
        append_alert("critical", f"pyfile:{rel_path}", msg)
        return CheckResult(f"pyfile:{rel_path}", False, "critical", msg, detail=detail)

    return CheckResult(f"pyfile:{rel_path}", True, "info",
                       f"{rel_path} ok ({line_count} lines)", detail=detail)


# ---- check: JSON state files --------------------------------------------

def check_json_state(rel_name: str, expected_type) -> CheckResult:
    p = REPO / rel_name
    if not p.exists():
        seed = {} if (expected_type is dict
                      or (isinstance(expected_type, tuple) and dict in expected_type)) \
               else []
        try:
            atomic_write_json(p, seed)
            msg = f"created missing {rel_name} with empty seed"
            log(msg, "warn")
            append_alert("warn", f"json:{rel_name}", msg, healed=True)
            return CheckResult(f"json:{rel_name}", True, "warn", msg, healed=True)
        except Exception as e:
            return CheckResult(f"json:{rel_name}", False, "error", f"seed failed: {e}")

    try:
        data = json.load(open(p, "r", encoding="utf-8"))
    except Exception as e:
        bak = p.with_suffix(".json.bak.raydoctor-corrupt")
        bak.write_bytes(p.read_bytes())
        seed = {} if expected_type is dict else []
        atomic_write_json(p, seed)
        msg = f"{rel_name} unparseable ({e}); backed up to {bak.name}, seeded empty"
        log(msg, "warn")
        append_alert("warn", f"json:{rel_name}", msg, healed=True)
        return CheckResult(f"json:{rel_name}", True, "warn", msg, healed=True)

    if isinstance(expected_type, tuple):
        ok_type = isinstance(data, expected_type)
    else:
        ok_type = isinstance(data, expected_type)
    if not ok_type:
        msg = f"{rel_name} has wrong type: {type(data).__name__}"
        append_alert("warn", f"json:{rel_name}", msg)
        return CheckResult(f"json:{rel_name}", False, "warn", msg)

    return CheckResult(f"json:{rel_name}", True, "info",
                       f"{rel_name} ok ({type(data).__name__})")


# ---- check: .env --------------------------------------------------------

def _load_env() -> dict:
    env: dict = {}
    p = REPO / ".env"
    if not p.exists():
        return env
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        if raw.startswith("﻿"):
            raw = raw[1:]
        for ln in raw.splitlines():
            t = ln.strip()
            if not t or t.startswith("#") or "=" not in t:
                continue
            k, v = t.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def check_env() -> CheckResult:
    env = _load_env()
    if not env:
        msg = ".env missing or unreadable at " + str(REPO / ".env")
        append_alert("critical", "env", msg)
        return CheckResult("env", False, "critical", msg)

    missing = [k for k in ENV_KEYS_REQUIRED if not env.get(k)]
    if missing:
        msg = f".env missing required keys: {missing}"
        append_alert("critical", "env", msg)
        return CheckResult("env", False, "critical", msg,
                           detail={"missing": missing, "present": list(env.keys())})

    kp = env["SOLANA_KEYPAIR_PATH"]
    kp_path = Path(kp).expanduser()
    if not kp_path.is_absolute():
        kp_path = REPO / kp_path
    if not kp_path.exists():
        msg = f"keypair file missing at {kp_path}"
        append_alert("critical", "env", msg)
        return CheckResult("env", False, "critical", msg)

    return CheckResult("env", True, "info",
                       f".env ok ({len(env)} keys; keypair resolves)")


# ---- check: Node bridge -------------------------------------------------

def check_node_bridge() -> CheckResult:
    candidates = [
        REPO / "src" / "raydium_lp1" / "raydium_clmm_node",
        REPO / "raydium_clmm_node",
    ]
    for nd in candidates:
        if not nd.exists():
            continue
        pkg = nd / "package.json"
        nm  = nd / "node_modules"
        mjs_files = list(nd.glob("*.mjs"))
        problems = []
        if not pkg.exists():
            problems.append("package.json missing")
        if not nm.exists():
            problems.append("node_modules missing (run `npm install`)")
        if len(mjs_files) < 3:
            problems.append(f"only {len(mjs_files)} .mjs files (expected >= 3)")
        if problems:
            msg = f"node bridge at {nd.name}: " + "; ".join(problems)
            append_alert("warn", "node_bridge", msg)
            return CheckResult("node_bridge", False, "warn", msg,
                               detail={"path": str(nd), "mjs_count": len(mjs_files)})
        return CheckResult("node_bridge", True, "info",
                           f"node bridge ok ({len(mjs_files)} .mjs files at {nd.name})")
    msg = "no raydium_clmm_node folder found under src/ or repo root"
    append_alert("warn", "node_bridge", msg)
    return CheckResult("node_bridge", False, "warn", msg)


# ---- check: dashboard ---------------------------------------------------

def resolve_dashboard_port() -> int:
    """LP1 dashboard default is 8844 (not legacy 8765)."""

    raw = (__import__("os").environ.get("LP1_DASHBOARD_PORT") or "").strip()
    if raw.isdigit():
        return int(raw)
    try:
        from raydium_lp1.settings_io import load_settings_json

        settings = load_settings_json(REPO / "config" / "settings.json")
        p = int(settings.get("dashboard_port") or 0)
        if p > 0:
            return p
    except Exception:
        pass
    return 8844


def check_dashboard(*, port: int | None = None, heal: bool = False) -> CheckResult:
    from raydium_lp1.doctor_dashboard_heal import heal_dashboard_server, resolve_dashboard_host

    port = port or resolve_dashboard_port()
    host = resolve_dashboard_host()
    ok, actions, msg = heal_dashboard_server(port=port, host=host, heal=heal)
    if ok:
        healed = bool(actions)
        if healed:
            append_alert("warn", "dashboard", msg, healed=True)
            return CheckResult(
                "dashboard",
                True,
                "warn",
                msg,
                healed=True,
                detail={"port": port, "host": host, "heal_actions": actions},
            )
        return CheckResult("dashboard", True, "info", msg, detail={"port": port, "host": host})

    append_alert("warn", "dashboard", msg, healed=bool(actions))
    return CheckResult(
        "dashboard",
        False,
        "warn",
        msg,
        healed=bool(actions),
        detail={"port": port, "host": host, "heal_actions": actions},
    )


# ---- driver -------------------------------------------------------------

def run_checks(*, heal: bool = True, heal_dashboard: bool | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    dash_heal = heal if heal_dashboard is None else heal_dashboard

    for rel, (min_lines, sentinel) in CRITICAL_PY_FILES.items():
        try:
            results.append(check_py_file(rel, min_lines, sentinel, heal=heal))
        except Exception as e:
            results.append(CheckResult(f"pyfile:{rel}", False, "error",
                                       f"check crashed: {e}\n{traceback.format_exc()[:300]}"))

    for rel, t in JSON_STATE_FILES.items():
        try:
            results.append(check_json_state(rel, t))
        except Exception as e:
            results.append(CheckResult(f"json:{rel}", False, "error", f"check crashed: {e}"))

    try:
        results.append(check_env())
    except Exception as e:
        results.append(CheckResult("env", False, "error", f"check crashed: {e}"))

    try:
        results.append(check_node_bridge())
    except Exception as e:
        results.append(CheckResult("node_bridge", False, "error", f"check crashed: {e}"))

    try:
        results.append(check_dashboard(heal=dash_heal))
    except Exception as e:
        results.append(CheckResult("dashboard", False, "warn", f"check crashed: {e}"))

    try:
        from raydium_lp1.doctor_data_flow_heal import heal_data_flow_integrity

        port = resolve_dashboard_port()
        # HTML/JSON/API sync is always auto-healed (unless explicitly disabled).
        df_heal = __import__("os").environ.get("RAYDIUM_LP1_DOCTOR_NO_DATAFLOW_HEAL", "").strip().lower() not in (
            "1",
            "true",
            "yes",
        )
        for df in heal_data_flow_integrity(heal=df_heal, dashboard_port=port):
            healed = bool(df.detail.get("healed"))
            msg = df.message
            if healed and df.detail.get("heal_actions"):
                msg = f"{msg} [healed: {', '.join(df.detail['heal_actions'][:3])}]"
            results.append(
                CheckResult(
                    f"dataflow:{df.name}",
                    df.ok,
                    df.severity,
                    msg,
                    healed=healed,
                    detail=df.detail,
                )
            )
    except Exception as e:
        results.append(CheckResult("dataflow", False, "warn", f"data flow checks crashed: {e}"))

    return results


def summarize(results: list[CheckResult]) -> dict:
    counts = {"info": 0, "warn": 0, "error": 0, "critical": 0}
    healed_count = 0
    for r in results:
        counts[r.severity] = counts.get(r.severity, 0) + 1
        if r.healed:
            healed_count += 1
    overall = "green"
    if counts.get("critical", 0): overall = "red"
    elif counts.get("error", 0):  overall = "red"
    elif counts.get("warn", 0):   overall = "yellow"
    return {
        "ts":       now_iso(),
        "overall":  overall,
        "counts":   counts,
        "healed":   healed_count,
        "checks":   [
            {"name": r.name, "ok": r.ok, "severity": r.severity,
             "message": r.message, "healed": r.healed, "detail": r.detail}
            for r in results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Raydium-LP1 doctor")
    ap.add_argument("--watch",    action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--json",     action="store_true")
    ap.add_argument("--heal", action="store_true", help="Force auto-repair on (overrides AI-edit pause)")
    ap.add_argument("--no-heal", action="store_true", help="Diagnose only; never rewrite files")
    ap.add_argument("--advise", action="store_true", help="Write reports/doctor_report.json profitability recommendations")
    args = ap.parse_args(argv)

    from raydium_lp1.doctor_heal_policy import (
        ai_edit_in_progress,
        should_auto_heal,
        should_heal_dashboard,
    )

    heal_enabled = should_auto_heal(cli_heal=args.heal, cli_no_heal=args.no_heal)
    dashboard_heal_enabled = should_heal_dashboard(cli_no_heal=args.no_heal, watch=args.watch)

    LOGS.mkdir(exist_ok=True)

    def one_pass() -> int:
        results = run_checks(heal=heal_enabled, heal_dashboard=dashboard_heal_enabled)
        summary = summarize(results)
        atomic_write_json(SNAPSHOT, summary)
        if args.advise:
            from raydium_lp1.doctor_advisor import write_doctor_report

            path = write_doctor_report(include_structural=True, heal=heal_enabled)
            log(f"advisor report -> {path}", "info")
        if args.json:
            payload = dict(summary)
            payload["heal_enabled"] = heal_enabled
            payload["dashboard_heal_enabled"] = dashboard_heal_enabled
            payload["ai_edit_paused_heal"] = ai_edit_in_progress() and not heal_enabled
            print(json.dumps(payload, indent=2))
        else:
            file_heal = "heal=ON" if heal_enabled else "heal=OFF (AI edit or --no-heal)"
            dash_heal = "dashboard_heal=ON" if dashboard_heal_enabled else "dashboard_heal=OFF"
            log(f"scan: overall={summary['overall']}  "
                f"counts={summary['counts']}  healed={summary['healed']}  {file_heal}  {dash_heal}",
                summary["overall"] if summary["overall"] != "green" else "info")
            for r in results:
                if r.severity in ("warn", "error", "critical"):
                    print(f"  [{r.severity:8s}] {r.name}: {r.message}")
        return 0 if summary["overall"] != "red" else 1

    if not args.watch:
        return one_pass()

    log(f"watch mode: scanning every {args.interval}s", "info")
    while True:
        try:
            one_pass()
        except Exception:
            log("scan crashed:\n" + traceback.format_exc(), "error")
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    sys.exit(main() or 0)
