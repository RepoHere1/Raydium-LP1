"""Run one emergency route-watch pass (5 checks / 24h scheduling)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    from raydium_lp1.emergency_route_watch import run_route_watch_pass
    from raydium_lp1.scanner import ScannerConfig, load_dotenv

    load_dotenv()
    config = ScannerConfig.from_file(REPO / "config" / "settings.json")
    report = run_route_watch_pass(config=config)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
