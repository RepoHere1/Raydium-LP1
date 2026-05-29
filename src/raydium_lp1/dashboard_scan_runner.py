"""Run scanner from the dashboard HTTP server (background thread)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
SCAN_SCRIPT = REPO / "scripts" / "scan_raydium_lps.py"
LOG_PATH = REPO / "reports" / "web_scan_console.log"

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "error": None,
    "summary": None,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_latest_summary() -> dict[str, Any] | None:
    path = REPO / "reports" / "latest.json"
    if not path.is_file():
        return None
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return {
            "scanned_at": data.get("scanned_at"),
            "candidate_count": data.get("candidate_count"),
            "rejected_count": data.get("rejected_count"),
            "scanned_count": data.get("scanned_count"),
            "mode": data.get("mode"),
        }
    except Exception:
        return None


def scan_status() -> dict[str, Any]:
    with _lock:
        return {
            "running": bool(_state["running"]),
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "exit_code": _state["exit_code"],
            "error": _state["error"],
            "summary": _state["summary"] or _read_latest_summary(),
        }


def _append_log(text: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(text)


def _run_scan_worker(*, write_rejections: bool) -> None:
    global _state
    started = _now_iso()
    _append_log(f"\n--- dashboard scan started {started} ---\n")
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [
        sys.executable,
        str(SCAN_SCRIPT),
        "--config",
        str(REPO / "config" / "settings.json"),
        "--write-reports",
        "--dashboard",
        "--check-rpc",
    ]
    if write_rejections:
        cmd.append("--write-rejections")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO),
            capture_output=True,
            text=True,
            env=env,
            timeout=3600,
        )
        if proc.stdout:
            _append_log(proc.stdout)
        if proc.stderr:
            _append_log(proc.stderr)
        summary = _read_latest_summary()
        with _lock:
            _state["exit_code"] = proc.returncode
            _state["finished_at"] = _now_iso()
            _state["summary"] = summary
            if proc.returncode != 0:
                _state["error"] = (proc.stderr or proc.stdout or "scan failed")[:500]
            else:
                _state["error"] = None
    except subprocess.TimeoutExpired:
        with _lock:
            _state["exit_code"] = -1
            _state["finished_at"] = _now_iso()
            _state["error"] = "scan timed out after 3600s"
    except Exception as exc:
        with _lock:
            _state["exit_code"] = -1
            _state["finished_at"] = _now_iso()
            _state["error"] = str(exc)
    finally:
        with _lock:
            _state["running"] = False
        _append_log(f"--- dashboard scan finished {_now_iso()} exit={_state.get('exit_code')} ---\n")


def start_dashboard_scan(*, write_rejections: bool = True) -> dict[str, Any]:
    """Start one scan pass in a daemon thread. Returns immediately."""

    with _lock:
        if _state["running"]:
            return {"ok": False, "error": "scan already running", "status": scan_status()}
        _state["running"] = True
        _state["started_at"] = _now_iso()
        _state["finished_at"] = None
        _state["exit_code"] = None
        _state["error"] = None
        _state["summary"] = None
    thread = threading.Thread(
        target=_run_scan_worker,
        kwargs={"write_rejections": write_rejections},
        daemon=True,
        name="dashboard-scan",
    )
    thread.start()
    return {"ok": True, "message": "scan started", "status": scan_status()}
