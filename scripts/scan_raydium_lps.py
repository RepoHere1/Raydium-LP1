#!/usr/bin/env python3
"""Command wrapper for the Raydium LP1 scanner."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raydium_lp1.scanner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
