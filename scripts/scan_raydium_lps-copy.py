#!/usr/bin/env python3
"""Command wrapper for the Raydium LP1 scanner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Matches raydium_lp1.scanner: paths are cwd-relative so run_scan.ps1 can Set-Location.
DEFAULT_CONFIG_PATH = Path("config/settings.json")
FALLBACK_CONFIG_PATH = Path("config/filters.example.json")


def _resolve_config_path(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_CONFIG_PATH and FALLBACK_CONFIG_PATH.exists():
        return FALLBACK_CONFIG_PATH
    return path


def _preflight_config(path: Path) -> None:
    """Fail early with readable errors (before heavy scanner imports)."""

    path = _resolve_config_path(path)
    if not path.exists():
        return
    try:
        from raydium_lp1.settings_io import load_settings_json

        load_settings_json(path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


def main() -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    known, _ = pre.parse_known_args()
    _preflight_config(known.config)

    from raydium_lp1.scanner import main as scanner_main  # noqa: E402

    return scanner_main()


if __name__ == "__main__":
    raise SystemExit(main())
