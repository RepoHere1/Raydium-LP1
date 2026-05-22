"""Run the looping scanner and the local HTTP dashboard in **one console**.

Starts ``scripts/scan_raydium_lps.py`` with ``--loop --dashboard --reload-config-each-scan``
as a child process, then serves ``raydium_lp1.dashboard_web`` on 127.0.0.1 (8844 by default).

Unless you pass ``--config``, the scanner reads ``config/settings.stack.json`` when that file
exists (demo-friendly ``min_apr`` and ``spawn_verdict_watcher``). On Windows, a true
``spawn_verdict_watcher`` opens ``scripts/watch_verdict.ps1`` in a new console, matching
``scripts/run_scan.ps1``. Scanner stdout/stderr are teed to ``reports/web_scan_console.log`` and
mirrored at ``/scan_log.html`` (browser opens that page when the stack starts).

Windows CMD::

    scripts\\start_stack.cmd

PowerShell::

    .\\scripts\\start_stack.ps1
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from raydium_lp1.dashboard_web import WEB_SCAN_CONSOLE_PATH, main as dash_main

REPO = Path(__file__).resolve().parents[2]


def _start_scanner_stdout_tee(proc: subprocess.Popen[bytes], log_path: Path, *, max_bytes: int = 2_500_000) -> None:
    """Mirror scanner stdout/stderr to the parent console and ``reports/web_scan_console.log``."""

    def runner() -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_path.write_bytes(b"")
        except OSError:
            pass
        stdout = proc.stdout
        if stdout is None:
            return
        try:
            while True:
                chunk = stdout.read(8192)
                if not chunk:
                    break
                try:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                except BrokenPipeError:
                    pass
                try:
                    with open(log_path, "ab") as lf:
                        lf.write(chunk)
                        lf.flush()
                except OSError:
                    pass
                try:
                    if log_path.stat().st_size > max_bytes:
                        tail = log_path.read_bytes()[-(max_bytes * 3 // 4) :]
                        log_path.write_bytes(tail)
                except OSError:
                    pass
        finally:
            try:
                stdout.close()
            except OSError:
                pass

    threading.Thread(target=runner, daemon=True, name="scanner-stdout-tee").start()


def _default_stack_config_path() -> Path:
    """Prefer committed stack preset (APR floor + watcher) over local settings.json."""

    if (REPO / "config" / "settings.stack.json").is_file():
        return Path("config/settings.stack.json")
    return Path("config/settings.json")


def _config_path_for_io(config_arg: Path) -> Path:
    return config_arg if config_arg.is_absolute() else (REPO / config_arg).resolve()


def _maybe_spawn_verdict_watcher(config_arg: Path) -> None:
    """Honor ``spawn_verdict_watcher`` the same way ``scripts/run_scan.ps1`` does (Windows)."""

    path = _config_path_for_io(config_arg)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not bool(raw.get("spawn_verdict_watcher")):
        return
    watch = REPO / "scripts" / "watch_verdict.ps1"
    if not watch.is_file():
        print("[stack] spawn_verdict_watcher is true but scripts/watch_verdict.ps1 is missing.", file=sys.stderr)
        return
    if sys.platform != "win32":
        print(
            "[stack] spawn_verdict_watcher is true; opening watch_verdict.ps1 is only automated on Windows. "
            "Tail reports/verdict_stream.log in another terminal.",
            file=sys.stderr,
        )
        return
    shell: str | None = None
    for name in ("pwsh.exe", "pwsh", "powershell.exe", "powershell"):
        shell = shutil.which(name)
        if shell:
            break
    if not shell:
        shell = "powershell.exe"
    creation = 0
    if hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        creation = subprocess.CREATE_NEW_CONSOLE
    try:
        subprocess.Popen(
            [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(watch),
            ],
            cwd=str(REPO),
            creationflags=creation,
        )
        print("[stack] Spawned verdict log watcher (second window).", file=sys.stderr)
    except OSError as exc:
        print(f"[stack] Could not spawn verdict watcher: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Raydium-LP1: one-window stack (scanner loop + dashboard HTTP).",
    )
    parser.add_argument("--no-scan", action="store_true", help="HTTP only; do not start the scanner child.")
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_stack_config_path(),
        help="Scanner settings JSON (default: config/settings.stack.json if present, else config/settings.json).",
    )
    parser.add_argument("--interval", type=int, default=60, help="Seconds between scans (loop mode).")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind address.")
    parser.add_argument("--port", type=int, default=8844, help="Dashboard port.")
    args, scan_extra = parser.parse_known_args(argv)
    print(f"[stack] Scanner --config {args.config}", file=sys.stderr)

    proc: subprocess.Popen[bytes] | None = None
    if not args.no_scan:
        cmd = [
            sys.executable,
            str(REPO / "scripts" / "scan_raydium_lps.py"),
            "--config",
            str(args.config),
            "--loop",
            "--interval",
            str(args.interval),
            "--dashboard",
            "--reload-config-each-scan",
            *scan_extra,
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO / "src")
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        _start_scanner_stdout_tee(proc, WEB_SCAN_CONSOLE_PATH)
        time.sleep(0.6)
        _maybe_spawn_verdict_watcher(args.config)

        def _stop_scanner() -> None:
            if proc is not None and proc.poll() is None:
                proc.terminate()

        atexit.register(_stop_scanner)

    dash_argv = ["--host", args.host, "--port", str(args.port)]
    if not args.no_scan:
        dash_argv += ["--open-browser", "/scan_log.html"]

    try:
        return int(dash_main(dash_argv))
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
