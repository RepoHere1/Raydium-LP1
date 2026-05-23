"""End-to-end demo for Raydium-LP1.

By default this runs a **live** dry-run scan against production Raydium
(``api-v3.raydium.io``) and the public Solana RPC fallback, then writes the
same report artifacts as a normal scan (``reports/latest.json``,
``reports/dashboard.json``, ``reports/data_provenance.json``, etc.).

Use ``--offline-mock`` only when you have no network: it swaps in canned JSON
for Raydium/RPC so CI or local development can still exercise the pipeline.

Neither mode signs transactions or sets ``dry_run`` false.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))
os.chdir(REPO_ROOT)

REPORTS = REPO_ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

history_path = REPORTS / "liquidity_history.json"

# Mocked Raydium API response with one healthy pool, one collapsing pool (offline only).
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
                "tvl": 800,
                "volume24h": 5,
                "mintA": {"symbol": "SOL", "address": "So11111111111111111111111111111111111111112"},
                "mintB": {"symbol": "RUG", "address": "RugMintAddressGoesHere111111111111111111111"},
            },
        ],
    }
}


def fake_rpc(url: str, payload: dict) -> dict:
    if payload.get("method") == "getBalance":
        return {"result": {"context": {"slot": 1}, "value": 320_000_000}}
    if payload.get("method") == "getHealth":
        return {"result": "ok"}
    return {"result": None}


def _live_demo_settings(*, with_routes: bool) -> dict:
    """Tuned for a single fast-ish live page while still using real Raydium + RPC verify."""

    return {
        "dry_run": True,
        "network": "solana",
        "strategy": "custom",
        "min_apr": 100.0,
        "apr_field": "apr24h",
        "pool_sort_field": "",
        "raydium_api_base": os.environ.get("RAYDIUM_API_BASE", "https://api-v3.raydium.io"),
        "pool_type": "all",
        "sort_type": "desc",
        "page_size": 100,
        "pages": 1,
        "http_timeout_seconds": 20,
        "page_delay_seconds": 0.25,
        "min_liquidity_usd": 500.0,
        "hard_exit_min_tvl_usd": 0.0,
        "min_volume_24h_usd": 50.0,
        "momentum_enabled": False,
        "max_position_usd": 25.0,
        "require_pool_id": True,
        "require_verified_raydium_pool": True,
        "verify_pool_on_chain": True,
        "verify_pool_raydium_api": False,
        "require_sell_route": with_routes,
        "route_sources": ["jupiter", "raydium"],
        "max_route_price_impact_pct": 30.0,
        "use_robust_routing": with_routes,
        "track_liquidity_health": True,
        "liquidity_history_path": str(history_path),
        "emergency_close_enabled": True,
        "emergency_alerts_path": str(REPORTS / "alerts.json"),
        "emergency_base_symbol": "SOL",
        "emergency_max_slippage_pct": 0.30,
        "position_size_sol": 0.1,
        "reserve_sol": 0.02,
        "allowed_quote_symbols": ["SOL", "USDC", "USDT"],
        "blocked_token_symbols": [],
        "blocked_mints": [],
        "solana_rpc_urls": [],
    }


def _offline_mock_settings() -> dict:
    # Canned pool ids are not real on-chain accounts; skip verify so offline mode
    # still exercises filters, health, emergency, and dashboard output.
    return {
        "dry_run": True,
        "network": "solana",
        "strategy": "aggressive",
        "min_apr": 100,
        "min_liquidity_usd": 100,
        "min_volume_24h_usd": 1,
        "require_verified_raydium_pool": False,
        "verify_pool_on_chain": False,
        "verify_pool_raydium_api": False,
        "require_sell_route": False,
        "use_robust_routing": False,
        "track_liquidity_health": True,
        "liquidity_history_path": str(history_path),
        "emergency_close_enabled": True,
        "emergency_alerts_path": str(REPORTS / "alerts.json"),
        "position_size_sol": 0.1,
        "reserve_sol": 0.02,
        "solana_rpc_urls": ["https://mock.rpc.invalid"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Raydium-LP1 end-to-end demo (live Raydium by default).")
    parser.add_argument(
        "--offline-mock",
        action="store_true",
        help="Use canned Raydium/RPC JSON instead of the network (for offline/CI only).",
    )
    parser.add_argument(
        "--with-routes",
        action="store_true",
        help="Live mode only: probe Jupiter/Raydium sell routes (much slower). Default skips route HTTP.",
    )
    args = parser.parse_args(argv)

    from raydium_lp1 import scanner  # noqa: E402

    if args.offline_mock:
        os.environ.setdefault("WALLET_ADDRESS", "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")
        os.environ.setdefault("WALLET_PRIVATE_KEY", "demo-not-real-key")
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
        config_path = REPORTS / "demo_settings.json"
        config_path.json.dumps(_offline_mock_settings(, indent=2), encoding="utf-8")
        with (
            patch("raydium_lp1.scanner.fetch_json", return_value=RAYDIUM_RESPONSE),
            patch("raydium_lp1.scanner.post_json", side_effect=fake_rpc),
            patch("raydium_lp1.wallet._default_rpc_post", side_effect=fake_rpc),
        ):
            return scanner.main(
                [
                    "--config",
                    str(config_path),
                    "--check-rpc",
                    "--write-reports",
                    "--dashboard",
                ]
            )

    # Live production data paths only; do not inject demo private keys.
    if "WALLET_PRIVATE_KEY" in os.environ and os.environ["WALLET_PRIVATE_KEY"].strip() == "demo-not-real-key":
        del os.environ["WALLET_PRIVATE_KEY"]
    if not history_path.exists():
        history_path."{}\n", encoding="utf-8"

    config_path = REPORTS / "demo_live_settings.json"
    config_path.write_text(
        json.dumps(_live_demo_settings(with_routes=args.with_routes), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        "[demo] LIVE mode: Raydium pool list + on-chain pool verify via your RPCs "
        f"(see {config_path}). Use --offline-mock for canned data.",
        flush=True,
    )
    return scanner.main(
        [
            "--config",
            str(config_path),
            "--check-rpc",
            "--write-reports",
            "--dashboard",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())

