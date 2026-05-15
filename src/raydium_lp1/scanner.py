"""Live Raydium liquidity-pool scanner with dry-run trade gating.

The scanner uses Raydium's public read-only API to find pools whose reported APR is
above a configured threshold, then applies local risk filters before anything can be
considered for a future buy/liquidity action.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from raydium_lp1 import dashboard as dashboard_mod
from raydium_lp1 import data_provenance
from raydium_lp1 import dial_in_analyst
from raydium_lp1 import emergency, health, networks, pool_verify, robust_routes, routes, strategies, verdicts, wallet as wallet_mod

RAYDIUM_API_BASE = "https://api-v3.raydium.io"
POOL_LIST_PATH = "/pools/info/list"
DEFAULT_CONFIG_PATH = Path("config/settings.json")
FALLBACK_CONFIG_PATH = Path("config/filters.example.json")
DEFAULT_ENV_PATH = Path(".env")
REPORTS_DIR = Path("reports")

# Hard ceiling so a typo like ``pages=5000`` in settings.json can't blow up
# into 5000 sequential blocking HTTP requests. Users who really want to scan
# more can bump this constant or run multiple short scans in --loop mode.
MAX_PAGES_HARD_CEILING = 50
MAX_PAGE_SIZE = 1000
DEFAULT_HTTP_TIMEOUT_SECONDS = 15
DEFAULT_PAGE_DELAY_SECONDS = 0.25


@dataclass(frozen=True)
class ScannerConfig:
    """Runtime filters used before a pool can become a candidate."""

    min_apr: float = 999.99
    apr_field: str = "apr24h"
    page_size: int = 100
    pages: int = 1
    http_timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS
    page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS
    pool_type: str = "all"
    sort_type: str = "desc"
    min_liquidity_usd: float = 1_000.0
    min_volume_24h_usd: float = 100.0
    max_position_usd: float = 25.0
    allowed_quote_symbols: set[str] = field(default_factory=lambda: {"SOL", "USDC", "USDT"})
    blocked_token_symbols: set[str] = field(default_factory=set)
    blocked_mints: set[str] = field(default_factory=set)
    require_pool_id: bool = True
    dry_run: bool = True
    raydium_api_base: str = RAYDIUM_API_BASE
    solana_rpc_urls: list[str] = field(default_factory=list)
    strategy: str = strategies.STRATEGY_CUSTOM
    require_sell_route: bool = True
    route_sources: tuple[str, ...] = ("jupiter", "raydium")
    # Raydium UI parity: pool age and LP burn-percent filters.
    max_pool_age_hours: float = 0.0  # 0 = disabled, otherwise only pools younger than this
    min_pool_age_hours: float = 0.0  # avoid 'too new' pools (helps you skip pre-launch dust)
    min_burn_percent: float = 0.0  # 0 = disabled, 100 = require fully burned LP
    track_liquidity_health: bool = True
    liquidity_history_path: str = "reports/liquidity_history.json"
    emergency_close_enabled: bool = True
    emergency_alerts_path: str = "reports/alerts.json"
    emergency_base_symbol: str = "SOL"
    emergency_max_slippage_pct: float = 0.30
    position_size_sol: float = 0.1
    reserve_sol: float = 0.02
    network: str = networks.NETWORK_SOLANA
    use_robust_routing: bool = True
    # Exit-safety: reject Jupiter quotes whose reported price impact exceeds this
    # (percent). 0 disables. Default 30 matches emergency_max_slippage_pct cap.
    max_route_price_impact_pct: float = 30.0
    # HARD reject when TVL is below this USD floor (0 = off). Use alongside
    # min_liquidity_usd for a clear "red line" message in CSV / stream.
    hard_exit_min_tvl_usd: float = 0.0
    # Write every reject row to CSV (pair, metrics, full reason text).
    write_rejections: bool = False
    rejections_csv_path: str = "reports/rejections.csv"
    # Reject pools that fail Raydium program + optional on-chain owner checks.
    require_verified_raydium_pool: bool = True
    verify_pool_on_chain: bool = True
    verify_pool_raydium_api: bool = False

    @classmethod
    def from_file(cls, path: Path) -> "ScannerConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        env_urls = split_env_list(os.environ.get("SOLANA_RPC_URLS", ""))
        single_env_url = os.environ.get("SOLANA_RPC_URL", "").strip()
        if single_env_url:
            env_urls.insert(0, single_env_url)
        config_urls = [str(value).strip() for value in raw.get("solana_rpc_urls", []) if str(value).strip()]
        env_strategy = os.environ.get("RAYDIUM_LP1_STRATEGY", "").strip() or None
        raw_with_strategy = strategies.apply_strategy(raw, env_strategy or raw.get("strategy"))
        return cls(
            min_apr=float(raw_with_strategy.get("min_apr", cls.min_apr)),
            apr_field=str(raw_with_strategy.get("apr_field", cls.apr_field)),
            page_size=_clamp_page_size(int(raw_with_strategy.get("page_size", cls.page_size))),
            pages=_clamp_pages(int(raw_with_strategy.get("pages", cls.pages))),
            http_timeout_seconds=max(3, int(raw_with_strategy.get("http_timeout_seconds", DEFAULT_HTTP_TIMEOUT_SECONDS))),
            page_delay_seconds=max(0.0, float(raw_with_strategy.get("page_delay_seconds", DEFAULT_PAGE_DELAY_SECONDS))),
            pool_type=str(raw_with_strategy.get("pool_type", cls.pool_type)),
            sort_type=str(raw_with_strategy.get("sort_type", cls.sort_type)),
            min_liquidity_usd=float(raw_with_strategy.get("min_liquidity_usd", cls.min_liquidity_usd)),
            min_volume_24h_usd=float(raw_with_strategy.get("min_volume_24h_usd", cls.min_volume_24h_usd)),
            max_position_usd=float(raw_with_strategy.get("max_position_usd", cls.max_position_usd)),
            allowed_quote_symbols=set(map(str.upper, raw_with_strategy.get("allowed_quote_symbols", ["SOL", "USDC", "USDT"]))),
            blocked_token_symbols=set(map(str.upper, raw_with_strategy.get("blocked_token_symbols", []))),
            blocked_mints=set(raw_with_strategy.get("blocked_mints", [])),
            require_pool_id=bool(raw_with_strategy.get("require_pool_id", True)),
            dry_run=bool(raw_with_strategy.get("dry_run", True)),
            raydium_api_base=str(raw_with_strategy.get("raydium_api_base") or os.environ.get("RAYDIUM_API_BASE") or RAYDIUM_API_BASE),
            solana_rpc_urls=dedupe([*env_urls, *config_urls]),
            strategy=strategies.normalize_strategy(str(raw_with_strategy.get("strategy", strategies.STRATEGY_CUSTOM))),
            require_sell_route=bool(raw_with_strategy.get("require_sell_route", True)),
            route_sources=tuple(
                str(s).strip().lower()
                for s in raw_with_strategy.get("route_sources", ["jupiter", "raydium"])
                if str(s).strip()
            )
            or ("jupiter", "raydium"),
            max_pool_age_hours=float(raw_with_strategy.get("max_pool_age_hours", 0.0)),
            min_pool_age_hours=float(raw_with_strategy.get("min_pool_age_hours", 0.0)),
            min_burn_percent=float(raw_with_strategy.get("min_burn_percent", 0.0)),
            track_liquidity_health=bool(raw_with_strategy.get("track_liquidity_health", True)),
            liquidity_history_path=str(
                raw_with_strategy.get("liquidity_history_path", "reports/liquidity_history.json")
            ),
            emergency_close_enabled=bool(raw_with_strategy.get("emergency_close_enabled", True)),
            emergency_alerts_path=str(
                raw_with_strategy.get("emergency_alerts_path", "reports/alerts.json")
            ),
            emergency_base_symbol=str(raw_with_strategy.get("emergency_base_symbol", "SOL")),
            emergency_max_slippage_pct=float(
                raw_with_strategy.get("emergency_max_slippage_pct", 0.30)
            ),
            position_size_sol=float(raw_with_strategy.get("position_size_sol", 0.1)),
            reserve_sol=float(raw_with_strategy.get("reserve_sol", 0.02)),
            network=networks.normalize_network(str(raw_with_strategy.get("network", "solana"))),
            use_robust_routing=bool(raw_with_strategy.get("use_robust_routing", True)),
            max_route_price_impact_pct=float(raw_with_strategy.get("max_route_price_impact_pct", 30.0)),
            hard_exit_min_tvl_usd=float(raw_with_strategy.get("hard_exit_min_tvl_usd", 0.0)),
            write_rejections=bool(raw_with_strategy.get("write_rejections", False)),
            rejections_csv_path=str(raw_with_strategy.get("rejections_csv_path", "reports/rejections.csv")),
            require_verified_raydium_pool=bool(
                raw_with_strategy.get("require_verified_raydium_pool", True)
            ),
            verify_pool_on_chain=bool(raw_with_strategy.get("verify_pool_on_chain", True)),
            verify_pool_raydium_api=bool(raw_with_strategy.get("verify_pool_raydium_api", False)),
        )


def _clamp_pages(requested: int) -> int:
    """Clamp ``pages`` to a sane upper bound; warn loudly when clamped."""

    if requested < 1:
        print(f"[config] pages={requested} is invalid; using 1.", file=sys.stderr)
        return 1
    if requested > MAX_PAGES_HARD_CEILING:
        print(
            f"[config] pages={requested} would issue {requested} blocking HTTP requests per scan-cycle. "
            f"Clamping to {MAX_PAGES_HARD_CEILING}. If you really want more, edit MAX_PAGES_HARD_CEILING "
            f"in src/raydium_lp1/scanner.py, but you almost certainly want --loop instead.",
            file=sys.stderr,
        )
        return MAX_PAGES_HARD_CEILING
    return requested


def _clamp_page_size(requested: int) -> int:
    if requested < 10:
        return 10
    if requested > MAX_PAGE_SIZE:
        print(
            f"[config] page_size={requested} exceeds Raydium's documented max ({MAX_PAGE_SIZE}); clamping.",
            file=sys.stderr,
        )
        return MAX_PAGE_SIZE
    return requested


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def split_env_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def load_dotenv(path: Path = DEFAULT_ENV_PATH) -> None:
    """Load simple KEY=value lines without requiring third-party packages."""

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def number(value: Any, default: float = 0.0) -> float:
    """Convert API numeric fields to floats without failing on blanks."""

    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def nested_get(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present top-level key from a Raydium pool payload."""

    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def token_symbol(token: Any) -> str:
    if isinstance(token, dict):
        raw = str(token.get("symbol") or token.get("name") or "").upper()
        # Raydium's API reports wrapped SOL as "WSOL". Treat it as SOL so the
        # default ``allowed_quote_symbols=["SOL", ...]`` actually matches.
        if raw == "WSOL":
            return "SOL"
        return raw
    return ""


def token_mint(token: Any) -> str:
    if isinstance(token, dict):
        return str(token.get("address") or token.get("mint") or token.get("id") or "")
    return ""


def pool_apr(pool: dict[str, Any], apr_field: str) -> float:
    """Read APR from Raydium's v3 response.

    The live API nests APR under ``day`` / ``week`` / ``month`` objects:
    ``pool["day"]["apr"]`` is total APR including reward emissions, while
    ``pool["day"]["feeApr"]`` is the trade-fee component. We add the reward
    APRs from ``rewardApr`` when available so the number lines up with what
    raydium.io displays in the liquidity-pools table.
    """

    period_key = "day"
    lookup = (apr_field or "").lower()
    if lookup in ("apr7d", "apr7", "week"):
        period_key = "week"
    elif lookup in ("apr30d", "apr30", "month"):
        period_key = "month"

    period_obj = pool.get(period_key)
    if isinstance(period_obj, dict):
        # Prefer the canonical "apr" if present; otherwise fee + rewards.
        if "apr" in period_obj and period_obj["apr"] is not None:
            return number(period_obj["apr"])
        fee_apr = number(period_obj.get("feeApr"))
        rewards = period_obj.get("rewardApr")
        if isinstance(rewards, list):
            fee_apr += sum(number(item) for item in rewards)
        if fee_apr:
            return fee_apr

    # Legacy / flat shapes (still used by some older endpoints and our own
    # mocked test fixtures).
    direct = number(pool.get(apr_field), default=-1.0)
    if direct >= 0:
        return direct
    apr_obj = pool.get("apr")
    if isinstance(apr_obj, dict):
        day = apr_field.removeprefix("apr")
        for key in (day, apr_field, day.lower()):
            value = number(apr_obj.get(key), default=-1.0)
            if value >= 0:
                return value
    return 0.0


def pool_volume(pool: dict[str, Any], apr_field: str) -> float:
    """Return 24h (or selected period) USD volume from a Raydium pool."""

    period_key = "day"
    lookup = (apr_field or "").lower()
    if lookup in ("apr7d", "apr7", "week"):
        period_key = "week"
    elif lookup in ("apr30d", "apr30", "month"):
        period_key = "month"
    period_obj = pool.get(period_key)
    if isinstance(period_obj, dict):
        return number(period_obj.get("volume"))
    # Legacy flat shape used by old fixtures.
    return number(
        pool.get("volume24h")
        or pool.get("volume24hUsd")
        or pool.get("dayVolume")
    )


def pool_fee_24h(pool: dict[str, Any]) -> float:
    period_obj = pool.get("day")
    if isinstance(period_obj, dict):
        return number(period_obj.get("volumeFee") or period_obj.get("fee"))
    return number(pool.get("fee24h") or pool.get("fee24hUsd"))


def normalize_pool(pool: dict[str, Any], apr_field: str) -> dict[str, Any]:
    """Project a Raydium v3 pool envelope into the flat dict the scanner uses.

    Reads nested period objects (``day`` / ``week`` / ``month``) for APR,
    volume and fees, and surfaces ``openTime``, ``burnPercent`` and pool
    type so feature filters can match what raydium.io's UI exposes.

    **Identifiers:** Raydium's API uses ``poolId`` / ``ammId`` / ``id`` (in that
    preference order here) for the pool's **on-chain state account**. Solana
    pubkeys all look like "wallets" — compare token mints (``mint_a`` /
    ``mint_b``) vs ``id`` vs ``lp_mint_address`` (LP receipt SPL mint when
    present).
    """

    mint_a = nested_get(pool, "mintA", "mint1", "baseMint", default={})
    mint_b = nested_get(pool, "mintB", "mint2", "quoteMint", default={})
    if not isinstance(mint_a, dict):
        mint_a = {}
    if not isinstance(mint_b, dict):
        mint_b = {}

    pool_type = str(nested_get(pool, "type", "poolType", default="") or "")
    pool_subtypes = pool.get("pooltype") if isinstance(pool.get("pooltype"), list) else []

    open_time_raw = pool.get("openTime") or pool.get("openTimestamp") or 0
    try:
        open_time_sec = int(open_time_raw)
    except (TypeError, ValueError):
        open_time_sec = 0

    lp_mint_obj = pool.get("lpMint") if isinstance(pool.get("lpMint"), dict) else {}
    lp_mint_address = str(lp_mint_obj.get("address") or "")
    cfg_obj = pool.get("config") if isinstance(pool.get("config"), dict) else {}
    config_account_id = str(cfg_obj.get("id") or "")
    pool_state_id = str(nested_get(pool, "poolId", "ammId", "id", default=""))

    return {
        "id": pool_state_id,
        "type": pool_type,
        "subtypes": list(pool_subtypes),
        "program_id": str(pool.get("programId") or ""),
        "apr": pool_apr(pool, apr_field),
        "fee_apr_24h": number(
            (pool.get("day") or {}).get("feeApr") if isinstance(pool.get("day"), dict) else 0
        ),
        "liquidity_usd": number(nested_get(pool, "tvl", "liquidity", "liquidityUsd", default=0)),
        "volume_24h_usd": pool_volume(pool, apr_field),
        "fee_24h_usd": pool_fee_24h(pool),
        "fee_rate": number(pool.get("feeRate")),
        "open_time": open_time_sec,
        "burn_percent": number(pool.get("burnPercent")),
        "launch_migrate_pool": bool(pool.get("launchMigratePool")),
        "farm_ongoing": int(pool.get("farmOngoingCount") or 0),
        "mint_a_symbol": token_symbol(mint_a),
        "mint_b_symbol": token_symbol(mint_b),
        "mint_a": token_mint(mint_a),
        "mint_b": token_mint(mint_b),
        "mint_a_decimals": int(mint_a.get("decimals") or 0) if isinstance(mint_a, dict) else 0,
        "mint_b_decimals": int(mint_b.get("decimals") or 0) if isinstance(mint_b, dict) else 0,
        "mint_a_tags": list(mint_a.get("tags") or []) if isinstance(mint_a, dict) else [],
        "mint_b_tags": list(mint_b.get("tags") or []) if isinstance(mint_b, dict) else [],
        "lp_mint_address": lp_mint_address,
        "config_account_id": config_account_id,
        "raw": pool,
    }


def extract_pool_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Handle common Raydium envelope formats."""

    data = response.get("data", response)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "list", "items", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def fetch_json(url: str, timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = Request(url, headers={"accept": "application/json", "user-agent": "Raydium-LP1/0.6"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - intentional public API read
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"API returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"API request failed for {url}: {reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"API request timed out after {timeout}s for {url}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"API returned invalid JSON for {url}: {exc}") from exc


def post_json(url: str, payload: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"content-type": "application/json", "accept": "application/json", "user-agent": "Raydium-LP1/0.2"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured RPC read
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc


def check_rpc_urls(urls: list[str]) -> list[dict[str, Any]]:
    """Ping configured Solana RPCs with getHealth for live-source diagnostics."""

    results: list[dict[str, Any]] = []
    for index, url in enumerate(urls, start=1):
        masked = mask_secret_url(url)
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
            response = post_json(url, payload)
            ok = response.get("result") == "ok" or "result" in response
            results.append({"index": index, "url": masked, "ok": ok, "response": response})
        except RuntimeError as exc:
            results.append({"index": index, "url": masked, "ok": False, "error": str(exc)})
    return results


def mask_secret_url(url: str) -> str:
    if "api-key=" in url:
        prefix, _, tail = url.partition("api-key=")
        return f"{prefix}api-key={tail[:4]}...MASKED"
    parts = url.rstrip("/").split("/")
    if len(parts) > 3 and len(parts[-1]) > 18:
        parts[-1] = f"{parts[-1][:6]}...MASKED"
        return "/".join(parts)
    return url


def pool_list_url(config: ScannerConfig, page: int = 1) -> str:
    params = {
        "poolType": config.pool_type,
        "poolSortField": config.apr_field,
        "sortType": config.sort_type,
        "pageSize": config.page_size,
        "page": page,
    }
    return f"{config.raydium_api_base.rstrip('/')}{POOL_LIST_PATH}?{urlencode(params)}"


def filter_pool(pool: dict[str, Any], config: ScannerConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if config.require_pool_id and not pool["id"]:
        reasons.append("missing pool id")

    if config.hard_exit_min_tvl_usd > 0 and pool["liquidity_usd"] < config.hard_exit_min_tvl_usd:
        reasons.append(
            f"HARD reject: TVL ${pool['liquidity_usd']:.2f} below exit-safety line "
            f"${config.hard_exit_min_tvl_usd:.2f} (too shallow to count on selling back to SOL)"
        )

    if pool["apr"] < config.min_apr:
        reasons.append(f"apr {pool['apr']:.2f} below {config.min_apr:.2f}")
    if pool["liquidity_usd"] < config.min_liquidity_usd:
        reasons.append(f"liquidity ${pool['liquidity_usd']:.2f} below ${config.min_liquidity_usd:.2f}")
    if pool["volume_24h_usd"] < config.min_volume_24h_usd:
        reasons.append(f"24h volume ${pool['volume_24h_usd']:.2f} below ${config.min_volume_24h_usd:.2f}")

    symbols = {pool["mint_a_symbol"], pool["mint_b_symbol"]} - {""}
    if config.allowed_quote_symbols and symbols.isdisjoint(config.allowed_quote_symbols):
        reasons.append(f"no allowed quote symbol in {sorted(symbols)}")
    blocked_symbols = symbols.intersection(config.blocked_token_symbols)
    if blocked_symbols:
        reasons.append(f"blocked symbol(s): {', '.join(sorted(blocked_symbols))}")

    mints = {pool["mint_a"], pool["mint_b"]} - {""}
    blocked_mints = mints.intersection(config.blocked_mints)
    if blocked_mints:
        reasons.append(f"blocked mint(s): {', '.join(sorted(blocked_mints))}")

    if config.max_pool_age_hours > 0 or config.min_pool_age_hours > 0:
        open_time = float(pool.get("open_time") or 0)
        if open_time > 0:
            age_hours = max(0.0, (time.time() - open_time) / 3600.0)
            if config.max_pool_age_hours > 0 and age_hours > config.max_pool_age_hours:
                reasons.append(
                    f"pool age {age_hours:.1f}h above max {config.max_pool_age_hours:.1f}h"
                )
            if config.min_pool_age_hours > 0 and age_hours < config.min_pool_age_hours:
                reasons.append(
                    f"pool age {age_hours:.1f}h below min {config.min_pool_age_hours:.1f}h"
                )

    if config.min_burn_percent > 0:
        burn = float(pool.get("burn_percent") or 0)
        if burn < config.min_burn_percent:
            reasons.append(
                f"LP burn {burn:.0f}% below min {config.min_burn_percent:.0f}%"
            )

    return not reasons, reasons


def assess_capacity(
    config: ScannerConfig,
    wallet_config: wallet_mod.WalletConfig | None,
    *,
    rpc_post: Any = None,
) -> dict[str, Any]:
    """Return wallet/capacity info: balance, max positions, reserved SOL.

    Safe to call when no wallet is configured or RPCs are unreachable; the
    result then reports ``ok=False`` and zero capacity instead of raising.
    """

    adapter = networks.get_adapter(config.network)
    network_info = adapter.to_dict()
    if wallet_config is None:
        return {
            "wallet": None,
            "network": network_info,
            "balance": {"ok": False, "error": "no wallet configured", "sol": 0.0, "lamports": 0},
            "capacity": wallet_mod.compute_capacity(
                0.0,
                position_size_sol=config.position_size_sol,
                reserve_sol=config.reserve_sol,
            ).to_dict(),
        }
    if not adapter.supports_live:
        return {
            "wallet": wallet_config.to_dict(),
            "network": network_info,
            "balance": {
                "ok": False,
                "error": f"{adapter.display_name} adapter is stub-only in this build",
                "sol": 0.0,
                "lamports": 0,
            },
            "capacity": wallet_mod.compute_capacity(
                0.0,
                position_size_sol=config.position_size_sol,
                reserve_sol=config.reserve_sol,
            ).to_dict(),
        }
    # Live path (Solana). For network adapters that aren't Solana we'd swap
    # this for a generic balance call once they support_live.
    if rpc_post is not None and isinstance(adapter, networks.SolanaAdapter):
        adapter.rpc_post = rpc_post  # type: ignore[assignment]
    balance_dict = adapter.fetch_native_balance(wallet_config.address, config.solana_rpc_urls)
    capacity = wallet_mod.compute_capacity(
        balance_dict.get("sol", 0.0) if balance_dict.get("ok") else 0.0,
        position_size_sol=config.position_size_sol,
        reserve_sol=config.reserve_sol,
    )
    return {
        "wallet": wallet_config.to_dict(),
        "network": network_info,
        "balance": balance_dict,
        "capacity": capacity.to_dict(),
    }


def scan(
    config: ScannerConfig,
    *,
    sellability_checker: Any = None,
    wallet_config: wallet_mod.WalletConfig | None = None,
    rpc_post: Any = None,
    verdict_stream: verdicts.StreamConfig | None = None,
    write_rejections_override: bool | None = None,
) -> dict[str, Any]:
    """Run a single scan pass.

    ``sellability_checker`` is overridable for tests. It receives the
    normalized pool dict and returns a :class:`routes.SellabilityResult`.
    ``write_rejections_override`` when set (non-``None``) forces rejection CSV
    on/off for this run regardless of ``config.write_rejections``.
    """

    from collections import Counter as _Counter
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    rejection_counts: _Counter = _Counter()
    reason_histogram: _Counter = _Counter()
    scanned = 0
    reject_idx = 0
    on_chain_owner_cache: dict[str, str | None] = {}
    stream_cfg = verdict_stream if verdict_stream is not None else verdicts.make_stream_config(enabled=False)
    if verdict_stream is not None and verdict_stream.enabled:
        verdict_stream.row_emit_count = 0

    adapter = networks.get_adapter(config.network)
    if not adapter.supports_live:
        # Non-Solana adapters are scaffolded but cannot actually scan yet.
        wallet_capacity_info = assess_capacity(config, wallet_config, rpc_post=rpc_post)
        return {
            "scanned_at": datetime.now(UTC).isoformat(),
            "mode": "dry_run",
            "strategy": config.strategy,
            "network": config.network,
            "network_info": adapter.to_dict(),
            "raydium_api_base": config.raydium_api_base,
            "min_apr": config.min_apr,
            "min_liquidity_usd": config.min_liquidity_usd,
            "min_volume_24h_usd": config.min_volume_24h_usd,
            "apr_field": config.apr_field,
            "scanned_count": 0,
            "candidate_count": 0,
            "candidate_count_pre_capacity": 0,
            "candidates_truncated": 0,
            "rejected_count": 0,
            "max_position_usd": config.max_position_usd,
            "rpc_count": len(config.solana_rpc_urls),
            "require_sell_route": config.require_sell_route,
            "route_sources": list(config.route_sources),
            "track_liquidity_health": config.track_liquidity_health,
            "health_summary": {"healthy": 0, "warning": 0, "critical": 0},
            "emergency_close_enabled": config.emergency_close_enabled,
            "triggered_alerts": [],
            "use_robust_routing": config.use_robust_routing,
            "route_cache_stats": robust_routes.get_global_cache().stats(),
            "wallet_capacity": wallet_capacity_info,
            "candidates": [],
            "rejected_preview": [],
            "rejection_breakdown": {},
            "rejection_reason_histogram": {},
            "rejections_csv": None,
            "notice": (
                f"Network {adapter.display_name!r} is scaffolded but not live yet. "
                "Switch back to network=solana to scan Raydium pools."
            ),
        }

    if sellability_checker is None and config.require_sell_route:
        max_impact = config.max_route_price_impact_pct if config.max_route_price_impact_pct > 0 else 0.0

        def _sell_check(p: dict) -> routes.SellabilityResult:
            return routes.check_pool_sellability(
                p,
                base_symbols=tuple(s.upper() for s in sorted(config.allowed_quote_symbols)),
                sources=config.route_sources,
                max_route_price_impact_pct=max_impact,
            )

        sellability_checker = _sell_check

    for page in range(1, config.pages + 1):
        url = pool_list_url(config, page=page)
        # Always announce the in-flight request so users can tell a slow
        # remote API apart from a hard hang.
        print(
            f"[scan] page {page}/{config.pages} (page_size={config.page_size}, "
            f"timeout={config.http_timeout_seconds}s)...",
            file=sys.stderr,
            flush=True,
        )
        response = fetch_json(url, timeout=config.http_timeout_seconds)
        items = extract_pool_items(response)
        if stream_cfg.enabled:
            verdicts.print_verdict_column_headers(stream_cfg, page=page)
        if page < config.pages and config.page_delay_seconds > 0:
            time.sleep(config.page_delay_seconds)
        page_pools = [normalize_pool(item, config.apr_field) for item in items]
        if config.verify_pool_on_chain:
            pool_verify.prefetch_account_owners(
                [str(p.get("id") or "") for p in page_pools if p.get("id")],
                config.solana_rpc_urls,
                owner_cache=on_chain_owner_cache,
                rpc_post=rpc_post,
            )
        for pool in page_pools:
            scanned += 1
            public_pool = {key: value for key, value in pool.items() if key != "raw"}
            if (
                config.require_verified_raydium_pool
                or config.verify_pool_on_chain
                or config.verify_pool_raydium_api
            ):
                verification = pool_verify.validate_pool(
                    public_pool,
                    api_base=config.raydium_api_base,
                    rpc_urls=config.solana_rpc_urls,
                    verify_on_chain=config.verify_pool_on_chain,
                    verify_raydium_api=config.verify_pool_raydium_api,
                    rpc_post=rpc_post,
                    owner_cache=on_chain_owner_cache,
                )
                public_pool["pool_verification"] = verification.to_dict()
                if config.require_verified_raydium_pool and not verification.ok:
                    verify_reasons = list(verification.reasons) or [
                        "not a verified Raydium pool state account (failed program/chain/API check)"
                    ]
                    verdicts.emit_reject(public_pool, verify_reasons, stream_cfg, idx=reject_idx)
                    reject_idx += 1
                    cat = verdicts._classify_reason(verify_reasons[0])
                    rejection_counts[cat] += 1
                    reason_histogram[verify_reasons[0][:200]] += 1
                    rejected.append({**public_pool, "reasons": verify_reasons})
                    continue
            ok, reasons = filter_pool(pool, config)
            if not ok:
                verdicts.emit_reject(public_pool, reasons, stream_cfg, idx=reject_idx)
                reject_idx += 1
                category = verdicts._classify_reason(reasons[0]) if reasons else "other"
                rejection_counts[category] += 1
                if reasons:
                    key = reasons[0][:200]
                    reason_histogram[key] += 1
                rejected.append({**public_pool, "reasons": reasons})
                continue

            if sellability_checker is not None:
                sell = sellability_checker(public_pool)
                public_pool["sellability"] = sell.to_dict()
                public_pool["sellability_log"] = routes.format_sellability_log(sell)
                if not sell.ok:
                    sell_reasons = list(sell.reasons)
                    verdicts.emit_reject(public_pool, sell_reasons, stream_cfg, idx=reject_idx)
                    reject_idx += 1
                    rejection_counts[verdicts._classify_reason(sell_reasons[0]) if sell_reasons else "other"] += 1
                    if sell_reasons:
                        reason_histogram[sell_reasons[0][:200]] += 1
                    rejected.append({**public_pool, "reasons": sell_reasons})
                    continue

            verdicts.emit_pass(public_pool, stream_cfg)
            candidates.append(public_pool)

    health_summary = {"healthy": 0, "warning": 0, "critical": 0}
    triggered_alerts: list[dict[str, Any]] = []
    if config.track_liquidity_health and candidates:
        history_path = Path(config.liquidity_history_path)
        assessments, _ = health.assess_pools(candidates, history_path=history_path)
        for pool, assessment in zip(candidates, assessments):
            pool["health"] = assessment.to_dict()
            health_summary[assessment.score] = health_summary.get(assessment.score, 0) + 1

        if config.emergency_close_enabled:
            alerts = emergency.run_emergency_pass(
                zip(candidates, assessments),
                base_symbol=config.emergency_base_symbol,
                max_slippage_pct=config.emergency_max_slippage_pct,
                alerts_path=Path(config.emergency_alerts_path),
                use_robust_routing=config.use_robust_routing,
            )
            triggered_alerts = [alert.to_dict() for alert in alerts]

    wallet_capacity_info = assess_capacity(config, wallet_config, rpc_post=rpc_post)
    max_positions = int(wallet_capacity_info["capacity"]["max_positions"]) if wallet_config is not None else None
    if wallet_config is not None and max_positions is not None:
        capped_candidates = candidates[:max_positions]
        candidates_truncated = max(0, len(candidates) - len(capped_candidates))
    else:
        capped_candidates = candidates
        candidates_truncated = 0

    do_write_rejections = (
        config.write_rejections if write_rejections_override is None else write_rejections_override
    )
    rejections_csv_written: str | None = None
    if do_write_rejections and rejected:
        rejections_csv_written = write_rejections_csv(
            rejected,
            scanned_at=datetime.now(UTC).isoformat(),
            path=Path(config.rejections_csv_path),
            reason_histogram=dict(reason_histogram.most_common(500)),
            breakdown=dict(rejection_counts),
        )
        print(
            f"[scan] wrote {len(rejected)} rejection row(s) -> {rejections_csv_written}",
            file=sys.stderr,
            flush=True,
        )

    provenance = data_provenance.build_provenance(config=config)
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "data_provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    return {
        "scanned_at": datetime.now(UTC).isoformat(),
        "mode": "dry_run" if config.dry_run else "trade_disabled_in_this_build",
        "data_provenance": provenance,
        "strategy": config.strategy,
        "network": config.network,
        "raydium_api_base": config.raydium_api_base,
        "min_apr": config.min_apr,
        "min_liquidity_usd": config.min_liquidity_usd,
        "min_volume_24h_usd": config.min_volume_24h_usd,
        "apr_field": config.apr_field,
        "scanned_count": scanned,
        "candidate_count": len(capped_candidates),
        "candidate_count_pre_capacity": len(candidates),
        "rejected_count": len(rejected),
        "max_position_usd": config.max_position_usd,
        "rpc_count": len(config.solana_rpc_urls),
        "require_sell_route": config.require_sell_route,
        "route_sources": list(config.route_sources),
        "track_liquidity_health": config.track_liquidity_health,
        "health_summary": health_summary,
        "emergency_close_enabled": config.emergency_close_enabled,
        "triggered_alerts": triggered_alerts,
        "use_robust_routing": config.use_robust_routing,
        "route_cache_stats": robust_routes.get_global_cache().stats(),
        "wallet_capacity": wallet_capacity_info,
        "candidates": capped_candidates,
        "candidates_truncated": candidates_truncated,
        "rejected_preview": rejected[:10],
        "rejection_breakdown": dict(rejection_counts),
        "rejection_reason_histogram": dict(reason_histogram.most_common(50)),
        "rejections_csv": rejections_csv_written,
    }


def print_reject_dial_in_hints(report: dict[str, Any]) -> None:
    """Echo reject reasons to stderr so they stay visible next to ``[scan]`` lines.

    On some Windows setups ``stdout`` is line-buffered or detached from the
    console view the user watches during long scans; stderr matches progress.
    """

    rej = int(report.get("rejected_count") or 0)
    if rej <= 0:
        return
    out = sys.stderr
    hist = report.get("rejection_reason_histogram") or {}
    bd = report.get("rejection_breakdown") or {}
    print("", file=out, flush=True)
    print(f"[reject-help] {rej} pool(s) rejected — why + how to tune:", file=out, flush=True)
    if not bd and not hist:
        print(
            "  [WARN] Report has no rejection_breakdown/histogram; use a current Raydium-LP1 build.",
            file=out,
            flush=True,
        )
    if hist:
        print("  Top first-reason strings (sample):", file=out, flush=True)
        for reason, n in list(hist.items())[:12]:
            short = reason if len(reason) <= 110 else reason[:107] + "..."
            print(f"    {n:>6}  {short}", file=out, flush=True)
    if report.get("rejections_csv"):
        csv_path = Path(report["rejections_csv"])
        summ = csv_path.with_name(csv_path.stem + ".summary.json")
        print(f"  Per-pool CSV: {csv_path}", file=out, flush=True)
        if summ.exists():
            print(f"  Summary JSON: {summ}", file=out, flush=True)
    else:
        print(
            '  Full export: run with --write-rejections or set "write_rejections": true in settings.json',
            file=out,
            flush=True,
        )


def print_report(report: dict[str, Any]) -> None:
    print("Raydium-LP1 live scan")
    print(f"Time: {report['scanned_at']}")
    print(f"Mode: {report['mode']}")
    print(f"Strategy: {report.get('strategy', 'custom')}")
    print(f"APR filter: {report['apr_field']} >= {report['min_apr']:.2f}%")
    print(f"Scanned: {report['scanned_count']} | Candidates: {report['candidate_count']} | Rejected: {report['rejected_count']}")
    print(f"Configured Solana RPCs: {report['rpc_count']}")
    print(f"Max future position size: ${report['max_position_usd']:.2f}")
    cap = report.get("wallet_capacity", {}).get("capacity", {})
    bal = report.get("wallet_capacity", {}).get("balance", {})
    if cap:
        print(
            f"Wallet: balance {bal.get('sol', 0):.4f} SOL | position_size {cap.get('position_size_sol', 0):.4f} SOL "
            f"-> max_positions={cap.get('max_positions', 0)} (reserved {cap.get('reserved_sol', 0):.4f} SOL)"
        )
        if report.get("candidates_truncated"):
            print(f"  ...{report['candidates_truncated']} candidate(s) hidden by capacity cap")
    if not report["candidates"]:
        print("No pools passed all filters. No action taken.")
        print_reject_dial_in_hints(report)
        return

    print("\nCandidates (dry-run watch list)")
    print(
        "Columns: PAIR_NAME | APR_PCT | TVL_USD | VOL24_USD | POOL_STATE "
        "(Raydium pool state pubkey — same base58 shape as any Solana account; not a token mint)"
    )
    hdr = f"{'PAIR_NAME':<32} | {'APR_PCT':>10} | {'TVL_USD':>12} | {'VOL24_USD':>14} | POOL_STATE"
    print(hdr)
    print("-" * min(160, len(hdr) + 20))
    for pool in report["candidates"]:
        pair = f"{pool['mint_a_symbol']}/{pool['mint_b_symbol']}"
        if len(pair) > 32:
            pair = pair[:29] + "..."
        pair = pair.ljust(32)
        proof = (pool.get("pool_verification") or {}).get("proof_tag", "?")
        print(
            f"{pair} | {float(pool['apr']):>10.2f} | {float(pool['liquidity_usd']):>12.2f} | "
            f"{float(pool['volume_24h_usd']):>14.2f} | {proof:<14} | {pool['id']}"
        )
    print("\nDry-run only: no buy, no wallet signing, no LP position opened.")


def write_reports(report: dict[str, Any], reports_dir: Path = REPORTS_DIR) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    latest_json = reports_dir / "latest.json"
    stamped_json = reports_dir / f"scan-{timestamp}.json"
    latest_csv = reports_dir / "candidates.csv"
    latest_diagnosis = reports_dir / "scan_diagnosis.json"
    payload = json.dumps(report, indent=2, sort_keys=True)
    latest_json.write_text(payload + "\n", encoding="utf-8")
    stamped_json.write_text(payload + "\n", encoding="utf-8")
    diag = report.get("scan_diagnosis")
    if isinstance(diag, dict):
        latest_diagnosis.write_text(
            json.dumps(diag, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    with latest_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scanned_at",
                "pool_id",
                "lp_mint_address",
                "config_account_id",
                "pool_proof",
                "raydium_verify_url",
                "pair",
                "apr",
                "liquidity_usd",
                "volume_24h_usd",
                "decision",
            ],
        )
        writer.writeheader()
        for pool in report["candidates"]:
            pv = pool.get("pool_verification") or {}
            writer.writerow(
                {
                    "scanned_at": report["scanned_at"],
                    "pool_id": pool["id"],
                    "lp_mint_address": pool.get("lp_mint_address", ""),
                    "config_account_id": pool.get("config_account_id", ""),
                    "pool_proof": pv.get("proof_tag", ""),
                    "raydium_verify_url": pv.get("raydium_verify_url", ""),
                    "pair": f"{pool['mint_a_symbol']}/{pool['mint_b_symbol']}",
                    "apr": pool["apr"],
                    "liquidity_usd": pool["liquidity_usd"],
                    "volume_24h_usd": pool["volume_24h_usd"],
                    "decision": "WATCH_ONLY_DRY_RUN",
                }
            )


def write_rejections_csv(
    rejected: list[dict[str, Any]],
    *,
    scanned_at: str,
    path: Path,
    reason_histogram: dict[str, int],
    breakdown: dict[str, int],
) -> str:
    """Write one CSV row per rejected pool plus a small JSON sidecar summary.

    Open in Excel / VS Code to sort and filter by ``first_reason`` while you
    tune ``settings.json``. The JSON file lists the top exact reasons and the
    category breakdown.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = path.with_suffix(".summary.json")
    fieldnames = [
        "scanned_at",
        "pool_id",
        "lp_mint_address",
        "config_account_id",
        "pool_proof",
        "on_chain_owner",
        "raydium_verify_url",
        "pair",
        "mint_a",
        "mint_b",
        "apr",
        "liquidity_usd",
        "volume_24h_usd",
        "burn_percent",
        "first_reason",
        "all_reasons",
        "sellability_log",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rejected:
            reasons = row.get("reasons") or []
            writer.writerow(
                {
                    "scanned_at": scanned_at,
                    "pool_id": row.get("id", ""),
                    "lp_mint_address": row.get("lp_mint_address", ""),
                    "config_account_id": row.get("config_account_id", ""),
                    "pool_proof": (row.get("pool_verification") or {}).get("proof_tag", ""),
                    "on_chain_owner": (row.get("pool_verification") or {}).get("on_chain_owner", ""),
                    "raydium_verify_url": (row.get("pool_verification") or {}).get("raydium_verify_url", ""),
                    "pair": f"{row.get('mint_a_symbol', '')}/{row.get('mint_b_symbol', '')}",
                    "mint_a": row.get("mint_a", ""),
                    "mint_b": row.get("mint_b", ""),
                    "apr": row.get("apr", 0),
                    "liquidity_usd": row.get("liquidity_usd", 0),
                    "volume_24h_usd": row.get("volume_24h_usd", 0),
                    "burn_percent": row.get("burn_percent", ""),
                    "first_reason": reasons[0] if reasons else "",
                    "all_reasons": " | ".join(reasons),
                    "sellability_log": row.get("sellability_log", ""),
                }
            )
    summary_path.write_text(
        json.dumps(
            {
                "scanned_at": scanned_at,
                "rejected_count": len(rejected),
                "breakdown_by_category": breakdown,
                "top_exact_first_reasons": reason_histogram,
                "csv": str(path.resolve()),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return str(path.resolve())


def resolve_config_path(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_CONFIG_PATH and FALLBACK_CONFIG_PATH.exists():
        return FALLBACK_CONFIG_PATH
    return path


def _init_verdict_mirror_log(vpath: Path) -> str:
    """Create or truncate the verdict mirror log and return its absolute path."""

    vpath.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    abs_path = str(vpath.resolve())
    header = (
        "# Raydium-LP1 verdict stream — plain-text mirror of PASS/REJECT lines (ANSI stripped)\n"
        f"# started {stamp}\n"
        "# Second PowerShell from repo root:  .\\scripts\\watch_verdict.ps1\n"
        f"# Or: Get-Content -LiteralPath '{abs_path}' -Wait -Tail 50\n\n"
    )
    vpath.write_text(header, encoding="utf-8")
    return abs_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan live Raydium LPs for extreme APR candidates.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to scanner JSON config.")
    parser.add_argument("--json", action="store_true", help="Print the scan report as JSON.")
    parser.add_argument("--loop", action="store_true", help="Keep scanning until stopped.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between scans in loop mode.")
    parser.add_argument("--write-reports", action="store_true", help="Write reports/latest.json and reports/candidates.csv.")
    parser.add_argument("--check-rpc", action="store_true", help="Check configured Solana RPC URLs with getHealth before scanning.")
    parser.add_argument(
        "--strategy",
        choices=list(strategies.ALLOWED_STRATEGIES),
        help="Override the strategy preset for this run (overrides settings.json).",
    )
    parser.add_argument("--list-strategies", action="store_true", help="Print the available strategy presets and exit.")
    parser.add_argument("--list-networks", action="store_true", help="Print the supported networks and exit.")
    parser.add_argument(
        "--quiet", action="store_true",
        help="Hide the per-pool PASS/REJECT stream (category breakdown still prints to stderr).",
    )
    parser.add_argument(
        "--verdict-stdout",
        action="store_true",
        help="Send PASS/REJECT lines and rejection breakdown to stdout (default is stderr).",
    )
    parser.add_argument(
        "--hide-passes", action="store_true",
        help="Hide green PASS lines, only show red REJECT decisions and the breakdown.",
    )
    parser.add_argument(
        "--show-rejects", type=int, default=200,
        help="Max red REJECT lines per scan (0 or negative = unlimited; can flood the terminal).",
    )
    parser.add_argument(
        "--write-rejections",
        action="store_true",
        help="Write reports/rejections.csv (+ .summary.json) with every pool and its reject reason(s).",
    )
    parser.add_argument(
        "--verdict-log",
        type=str,
        default="",
        metavar="PATH",
        help="Overwrite PATH at start, then append plain-text PASS/REJECT lines. If omitted, "
        "writes reports/verdict_stream.log whenever the live stream is on (see --no-verdict-log).",
    )
    parser.add_argument(
        "--no-verdict-log",
        action="store_true",
        help="Do not write reports/verdict_stream.log (only applies when --verdict-log is not set).",
    )
    parser.add_argument(
        "--verdict-header-every",
        type=int,
        default=25,
        metavar="N",
        help="Re-print the full verdict table header (same widths as data rows) every N "
        "PASS/REJECT rows on stderr (0 disables).",
    )
    parser.add_argument(
        "--wallet-override",
        type=str,
        default=None,
        help="Use a different wallet public address for this run (does not modify .env).",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Render the unified dashboard text and write reports/dashboard.json.",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable dashboard output even if it would otherwise run.",
    )
    args = parser.parse_args(argv)

    if args.list_strategies:
        print(strategies.describe_presets())
        return 0
    if args.list_networks:
        print(networks.describe_networks())
        return 0

    load_dotenv()
    if args.strategy:
        os.environ["RAYDIUM_LP1_STRATEGY"] = args.strategy
    config_path = resolve_config_path(args.config)
    config = ScannerConfig.from_file(config_path)
    if not config.dry_run:
        print("Refusing to run: this build is dry-run only. Set dry_run=true.", file=sys.stderr)
        return 2

    try:
        active_wallet = wallet_mod.load_wallet()
    except wallet_mod.WalletError as exc:
        print(f"Wallet config error: {exc}", file=sys.stderr)
        return 2
    if args.wallet_override:
        try:
            active_wallet = wallet_mod.override_wallet(args.wallet_override)
        except wallet_mod.WalletError as exc:
            print(f"--wallet-override rejected: {exc}", file=sys.stderr)
            return 2
    if active_wallet is not None:
        print(f"Wallet: {active_wallet.address} (source={active_wallet.source})")

    rpc_results: list[dict[str, Any]] = []
    if args.check_rpc:
        rpc_results = check_rpc_urls(config.solana_rpc_urls)
        print(json.dumps({"rpc_results": rpc_results}, indent=2))

    show_dashboard = args.dashboard and not args.no_dashboard
    cap = int(args.show_rejects)
    if cap <= 0:
        cap = 10**7

    interactive_stream = not args.quiet and not args.json
    explicit_log = (args.verdict_log or "").strip()
    verdict_log_resolved: str | None = None
    if explicit_log:
        verdict_log_resolved = _init_verdict_mirror_log(Path(explicit_log))
    elif interactive_stream and not args.no_verdict_log:
        verdict_log_resolved = _init_verdict_mirror_log(REPORTS_DIR / "verdict_stream.log")

    if interactive_stream:
        print(
            "[scan] STDERR = live pages + PASS/REJECT table + breakdown. "
            "STDOUT = summary + candidates table.",
            file=sys.stderr,
            flush=True,
        )
        print(data_provenance.print_live_sources_banner(config), file=sys.stderr, flush=True)
        print(
            "[scan] POOL_STATE + PROOF: Raydium pool state pubkey; PROOF e.g. CPMM+chain = live RPC owner matches "
            "Raydium program (NOT a user wallet). Dust/scam pools can still verify as CPMM but fail TVL/APR filters.",
            file=sys.stderr,
            flush=True,
        )
        if verdict_log_resolved:
            print(
                f"[scan] Verdict mirror log (tail in a 2nd window): {verdict_log_resolved}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                "[scan] Verdict mirror log disabled (--no-verdict-log).",
                file=sys.stderr,
                flush=True,
            )

    verdict_stream = sys.stdout if args.verdict_stdout else None
    stream_cfg = verdicts.make_stream_config(
        enabled=not args.quiet and not args.json,
        show_passes=not args.hide_passes,
        max_rejections_shown=cap,
        stream=verdict_stream,
        verdict_log_path=verdict_log_resolved,
        header_repeat_rows=int(args.verdict_header_every),
    )
    wr_override = True if args.write_rejections else None

    while True:
        try:
            report = scan(
                config,
                wallet_config=active_wallet,
                verdict_stream=stream_cfg,
                write_rejections_override=wr_override,
            )
        except RuntimeError as exc:
            print(f"Scan failed: {exc}", file=sys.stderr)
            return 1

        report["scan_diagnosis"] = dial_in_analyst.build_scan_diagnosis(config, report)

        verdicts.print_rejection_breakdown(report.get("rejection_breakdown") or {}, stream_cfg)
        if not args.json:
            dial_in_analyst.print_scan_diagnosis(report["scan_diagnosis"], stream_cfg=stream_cfg)

        if args.write_reports:
            write_reports(report)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print_report(report)

        if show_dashboard:
            data = dashboard_mod.build_dashboard(
                config=config,
                report=report,
                rpc_health=rpc_results,
                alerts_path=Path(config.emergency_alerts_path),
            )
            dashboard_mod.write_dashboard(data)
            print("")
            dashboard_mod.print_dashboard(data)

        if not args.loop:
            return 0
        if stream_cfg.verdict_log_path:
            verdicts.log_between_scan_cycles(stream_cfg, iso_timestamp=datetime.now(UTC).isoformat())
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
