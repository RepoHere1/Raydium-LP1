"""Document which scanner outputs are live API/RPC vs modeled / dry-run only."""

from __future__ import annotations

from typing import Any

from raydium_lp1 import pool_verify, routes, robust_routes

RAYDIUM_API_BASE = "https://api-v3.raydium.io"
POOL_LIST_PATH = "/pools/info/list"

# Registry of non-live or partially-modeled behavior in src/raydium_lp1 (not tests).
NON_LIVE_COMPONENTS: list[dict[str, str]] = [
    {
        "module": "scanner.py",
        "what": "Pool list APR/TVL/volume/mints",
        "source": "LIVE",
        "detail": f"GET {{raydium_api_base}}{POOL_LIST_PATH} (Raydium api-v3)",
    },
    {
        "module": "pool_verify.py",
        "what": "POOL_STATE / pool id authenticity",
        "source": "LIVE",
        "detail": "RPC getAccountInfo/getMultipleAccounts owner + optional Raydium /pools/info/ids",
    },
    {
        "module": "routes.py",
        "what": "Sell-route probes",
        "source": "LIVE",
        "detail": f"Jupiter {routes.JUPITER_QUOTE_URL}, Raydium {routes.RAYDIUM_COMPUTE_URL}",
    },
    {
        "module": "robust_routes.py",
        "what": "Extra route quotes + cache",
        "source": "LIVE",
        "detail": f"Orca {robust_routes.ORCA_QUOTE_URL}, Raydium AMM quote; 5m cache",
    },
    {
        "module": "wallet.py",
        "what": "SOL balance / capacity",
        "source": "LIVE",
        "detail": "RPC getBalance when wallet + RPC configured; else zeros",
    },
    {
        "module": "emergency.py",
        "what": "Emergency swap plans",
        "source": "MODELED",
        "detail": "Dry-run quotes; position_token_amount=1_000_000 placeholder (line ~178)",
    },
    {
        "module": "dial_in_analyst.py",
        "what": "Filter tuning suggestions",
        "source": "MODELED",
        "detail": "Heuristics from rejection counts — not market predictions",
    },
    {
        "module": "networks.py",
        "what": "Ethereum / Base scanning",
        "source": "STUB",
        "detail": "No live DEX adapter; Solana/Raydium only",
    },
    {
        "module": "lp_range_planner.py",
        "what": "CLMM band / budget suggestions",
        "source": "MODELED",
        "detail": "Heuristic widths + momentum skew from public list fields; not on-chain tick math; no signed txs",
    },
    {
        "module": "scanner.py",
        "what": "Trade execution",
        "source": "DISABLED",
        "detail": "dry_run=true required; no signed swaps in this build",
    },
]


def build_provenance(*, config: Any, verified_sample: dict[str, Any] | None = None) -> dict[str, Any]:
    """JSON-serializable audit blob written to reports/data_provenance.json."""

    return {
        "live_endpoints": {
            "raydium_pool_list": f"{getattr(config, 'raydium_api_base', RAYDIUM_API_BASE).rstrip('/')}{POOL_LIST_PATH}",
            "raydium_pool_by_id": f"{getattr(config, 'raydium_api_base', RAYDIUM_API_BASE).rstrip('/')}{pool_verify.RAYDIUM_POOL_INFO_IDS}?ids=<POOL_STATE>",
            "jupiter_quote": routes.JUPITER_QUOTE_URL,
            "raydium_swap_compute": routes.RAYDIUM_COMPUTE_URL,
            "orca_quote": robust_routes.ORCA_QUOTE_URL,
            "solana_rpc": list(getattr(config, "solana_rpc_urls", []) or []) or [pool_verify.DEFAULT_PUBLIC_RPC],
        },
        "verification_settings": {
            "require_verified_raydium_pool": getattr(config, "require_verified_raydium_pool", True),
            "verify_pool_on_chain": getattr(config, "verify_pool_on_chain", True),
            "verify_pool_raydium_api": getattr(config, "verify_pool_raydium_api", False),
        },
        "known_raydium_pool_programs": dict(pool_verify.RAYDIUM_POOL_PROGRAMS),
        "non_live_components": list(NON_LIVE_COMPONENTS),
        "explorer_note": (
            "Solana explorers label many account types as 'wallet'. Raydium pool state accounts "
            "are owned by CPMM/CLMM/AMM programs — use PROOF column (e.g. CPMM+chain) not explorer labels."
        ),
        "verified_sample": verified_sample,
    }


def print_live_sources_banner(config: Any) -> str:
    """One-line stderr summary of live data sources."""

    prov = build_provenance(config=config)
    live = prov["live_endpoints"]
    return (
        "[scan] LIVE data: Raydium pool list + optional /pools/info/ids; "
        f"on-chain owner via RPC; routes via Jupiter/Raydium/Orca. "
        f"Pool programs: {', '.join(sorted(set(pool_verify.RAYDIUM_POOL_PROGRAMS.values())))}. "
        "See reports/data_provenance.json for full audit."
    )
