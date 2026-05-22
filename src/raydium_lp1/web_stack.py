"""Run the looping scanner and the local HTTP dashboard in **one console**.

Starts ``scripts/scan_raydium_lps.py`` with ``--loop --dashboard --reload-config-each-scan``
as a child process, then serves ``raydium_lp1.dashboard_web`` on 127.0.0.1 (8844 by default).

Windows CMD::

    scripts\\start_stack.cmd

PowerShell::

    .\\scripts\\start_stack.ps1
"""

from __future__ import annotations

import argparse
import atexit
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Raydium-LP1: one-window stack (scanner loop + dashboard HTTP).",
    )
    parser.add_argument("--no-scan", action="store_true", help="HTTP only; do not start the scanner child.")
    parser.add_argument("--config", type=Path, default=Path("config/settings.json"))
    parser.add_argument("--interval", type=int, default=60, help="Seconds between scans (loop mode).")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind address.")
    parser.add_argument("--port", type=int, default=8844, help="Dashboard port.")
    args, scan_extra = parser.parse_known_args(argv)

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
        proc = subprocess.Popen(cmd, cwd=str(REPO), env=env)

        def _stop_scanner() -> None:
            if proc is not None and proc.poll() is None:
                proc.terminate()

        atexit.register(_stop_scanner)

    from raydium_lp1.dashboard_web import main as dash_main

    try:
        return int(dash_main(["--host", args.host, "--port", str(args.port)]))
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
