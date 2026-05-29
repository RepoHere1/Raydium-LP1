"""Autonomous heal: restart dashboard HTTP on :8844 when /health is down."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
LOGS = REPO / "logs"
STATE_PATH = LOGS / "doctor_dashboard_heal_state.json"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8844
MIN_RETRY_SEC = 25.0
MAX_ATTEMPTS_WINDOW = 5
ATTEMPT_WINDOW_SEC = 300.0
STARTUP_WAIT_SEC = 75.0


def resolve_dashboard_host() -> str:
    raw = (os.environ.get("LP1_DASHBOARD_HOST") or "").strip()
    if raw:
        return raw
    return DEFAULT_HOST


def probe_dashboard(
    *,
    host: str,
    port: int,
    timeout: float = 3.0,
) -> tuple[bool, str | None, str | None]:
    """Return (ok, path_that_worked, last_error)."""

    last_err: str | None = None
    for path in ("/health", "/api/runtime"):
        url = f"http://{host}:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if resp.status == 200:
                    return True, path, None
        except urllib.error.URLError as e:
            last_err = str(e.reason or e)
        except Exception as e:
            last_err = str(e)
    return False, None, last_err


def _read_state() -> dict[str, Any]:
    try:
        if STATE_PATH.is_file():
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except (OSError, json.JSONDecodeError):
        pass
    return {"attempts": []}


def _write_state(state: dict[str, Any]) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _prune_attempts(attempts: list[float], now: float) -> list[float]:
    cutoff = now - ATTEMPT_WINDOW_SEC
    return [t for t in attempts if t >= cutoff]


def heal_rate_limited() -> tuple[bool, str]:
    """Return (allowed, reason_if_blocked)."""

    now = time.time()
    state = _read_state()
    attempts = _prune_attempts(list(state.get("attempts") or []), now)
    if attempts and (now - attempts[-1]) < MIN_RETRY_SEC:
        wait = int(MIN_RETRY_SEC - (now - attempts[-1]) + 1)
        return False, f"cooldown ({wait}s since last restart attempt)"
    if len(attempts) >= MAX_ATTEMPTS_WINDOW:
        return False, f"rate limit ({MAX_ATTEMPTS_WINDOW} restarts in {int(ATTEMPT_WINDOW_SEC)}s)"
    return True, ""


def _record_attempt_start() -> None:
    now = time.time()
    state = _read_state()
    attempts = _prune_attempts(list(state.get("attempts") or []), now)
    attempts.append(now)
    state["attempts"] = attempts
    state["last_attempt"] = now
    _write_state(state)


def _record_attempt_success() -> None:
    state = _read_state()
    state["last_success"] = time.time()
    _write_state(state)


def _run_powershell_script(script: Path, *extra_args: str) -> tuple[int, str]:
    if not script.is_file():
        return 1, f"missing script: {script}"
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *extra_args,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 1, "powershell timed out"
    except Exception as e:
        return 1, str(e)


def stop_dashboard_port(port: int) -> list[str]:
    actions: list[str] = []
    stop_script = REPO / "scripts" / "stop_dashboard_port.ps1"
    if sys.platform == "win32" and stop_script.is_file():
        code, detail = _run_powershell_script(stop_script, "-Port", str(port))
        actions.append(f"stop_dashboard_port.ps1 exit={code}")
        if detail:
            actions.append(detail.splitlines()[0][:120])
        time.sleep(1.0)
        return actions

    # Non-Windows fallback: nothing to kill safely without psutil.
    actions.append("skip port stop (non-Windows)")
    return actions


def start_dashboard_process(*, host: str, port: int) -> list[str]:
    actions: list[str] = []
    dash_script = REPO / "scripts" / "run_dashboard_web.ps1"
    if sys.platform == "win32" and dash_script.is_file():
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(dash_script),
            "-Port",
            str(port),
            "-ListenHost",
            host,
        ]
        flags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
        subprocess.Popen(cmd, cwd=str(REPO), creationflags=flags)
        actions.append(f"started run_dashboard_web.ps1 on {host}:{port}")
        return actions

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    subprocess.Popen(
        [sys.executable, "-m", "raydium_lp1.dashboard_web", "--host", host, "--port", str(port)],
        cwd=str(REPO),
        env=env,
    )
    actions.append(f"started dashboard_web on {host}:{port}")
    return actions


def wait_dashboard_ready(*, host: str, port: int, timeout: float = STARTUP_WAIT_SEC) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok, _, _ = probe_dashboard(host=host, port=port, timeout=3.0)
        if ok:
            return True
        time.sleep(1.0)
    return False


def heal_dashboard_server(
    *,
    port: int,
    host: str | None = None,
    heal: bool = True,
) -> tuple[bool, list[str], str]:
    """
    Ensure dashboard responds on /health.
    Returns (ok_after, actions_taken, message).
    """

    host = host or resolve_dashboard_host()
    ok, path, err = probe_dashboard(host=host, port=port)
    if ok:
        return True, [], f"dashboard reachable on :{port} ({path})"

    if not heal:
        msg = (
            f"dashboard not reachable on :{port} ({err or 'no response'}). "
            f"Start: .\\scripts\\run_dashboard_web.ps1  (http://{host}:{port}/)"
        )
        return False, [], msg

    allowed, block_reason = heal_rate_limited()
    if not allowed:
        msg = (
            f"dashboard not reachable on :{port} ({err or 'no response'}); "
            f"heal paused: {block_reason}"
        )
        return False, [], msg

    actions: list[str] = []
    actions.extend(stop_dashboard_port(port))
    actions.extend(start_dashboard_process(host=host, port=port))
    _record_attempt_start()

    if wait_dashboard_ready(host=host, port=port):
        _record_attempt_success()
        ok2, path2, _ = probe_dashboard(host=host, port=port)
        if ok2:
            msg = (
                f"dashboard healed on :{port} ({path2}) "
                f"[restarted: {', '.join(actions[:2])}]"
            )
            return True, actions, msg

    msg = (
        f"dashboard still down on :{port} after restart attempt "
        f"({', '.join(actions[:2])}). Check logs in Dashboard window."
    )
    return False, actions, msg
