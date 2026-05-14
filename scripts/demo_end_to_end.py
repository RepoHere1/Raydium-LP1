"""End-to-end demo for Raydium-LP1.

This script exercises every feature added in this branch using mocked
Raydium / Jupiter / RPC responses so it works offline. It prints the
full dashboard and writes a complete set of artifacts under reports/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))
os.chdir(REPO_ROOT)

# Ensure no leftover env wallet config from a previous run.
os.environ.setdefault("WALLET_ADDRESS", "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")
os.environ.setdefault("WALLET_PRIVATE_KEY", "demo-not-real-key")

from raydium_lp1 import dashboard, emergency, health, scanner  # noqa: E402

REPORTS = REPO_ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

# Seed liquidity history so one pool comes out CRITICAL on the next scan.
history_path = REPORTS / "liquidity_history.json"
history_path.write_text(
    json.dumps(
        {
            "rugpool": {
                "pair": "SOL/RUG",
                "entry": {"tvl": 10_000, "volume_24h": 5_000, "apr": 1_200, "ts": "t0"},
                "snapshots": [
                    {"tvl": 10_000, "volume_24h": 5_000, "apr": 1_200, "ts": "t0"}
                ],
                "last_seen": "t0",
            }
        },
        indent=2,
    ),
    encoding="utf-8",
)

# Mocked Raydium API response with one healthy pool, one collapsing pool.
RAYDIUM_RESPONSE = {
    "data": {
        "count": 2,
        "data": [
            {
                "id": "good-pool",
                "apr24h": 1500,
                "tvl": 8_500,
                "volume24h": 2_500,
                "mintA": {"symbol": "SOL", "address": "So11111111111111111111111111111111111111112"},
                "mintB": {"symbol": "MEME", "address": "MemEMintAddressGoesHere111111111111111111111"},
            },
            {
                "id": "rugpool",
                "apr24h": 4000,
                "tvl": 800,  # 92% TVL drop vs seeded entry
                "volume24h": 5,  # near zero
                "mintA": {"symbol": "SOL", "address": "So11111111111111111111111111111111111111112"},
                "mintB": {"symbol": "RUG", "address": "RugMintAddressGoesHere111111111111111111111"},
            },
        ],
    }
}


def fake_rpc(url: str, payload: dict) -> dict:
    if payload.get("method") == "getBalance":
        return {"result": {"context": {"slot": 1}, "value": 320_000_000}}  # 0.32 SOL
    if payload.get("method") == "getHealth":
        return {"result": "ok"}
    return {"result": None}


def main() -> int:
    config_path = REPORTS / "demo_settings.json"
    config_path.write_text(
        json.dumps(
            {
                "dry_run": True,
                "network": "solana",
                "strategy": "aggressive",
                "min_apr": 100,
                "min_liquidity_usd": 100,
                "min_volume_24h_usd": 1,
                "require_sell_route": False,  # skip live HTTP probes in the demo
                "use_robust_routing": False,  # ditto
                "track_liquidity_health": True,
                "liquidity_history_path": str(history_path),
                "emergency_close_enabled": True,
                "emergency_alerts_path": str(REPORTS / "alerts.json"),
                "position_size_sol": 0.1,
                "reserve_sol": 0.02,
                "solana_rpc_urls": ["https://mock.rpc.example"],
            },
            indent=2,
        )
    )

    with (
        patch("raydium_lp1.scanner.fetch_json", return_value=RAYDIUM_RESPONSE),
        patch("raydium_lp1.scanner.post_json", side_effect=fake_rpc),
        patch("raydium_lp1.wallet._default_rpc_post", side_effect=fake_rpc),
    ):
        rc = scanner.main(
            [
                "--config",
                str(config_path),
                "--check-rpc",
                "--write-reports",
                "--dashboard",
            ]
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
