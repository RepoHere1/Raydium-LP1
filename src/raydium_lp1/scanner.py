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

from .honeypot_guard import (
    HoneypotGuardConfig,
    MintInspection,
    evaluate_honeypot_guard,
)
from .quote_only_entry import (
    QuoteOnlyEntryConfig,
    base_side,
    evaluate_quote_only_entry,
)
from .survival_runway import SurvivalRunwayConfig, evaluate_survival_runway

RAYDIUM_API_BASE = "https://api-v3.raydium.io"
POOL_LIST_PATH = "/pools/info/list"
DEFAULT_CONFIG_PATH = Path("config/settings.json")
FALLBACK_CONFIG_PATH = Path("config/filters.example.json")
DEFAULT_ENV_PATH = Path(".env")
REPORTS_DIR = Path("reports")


@dataclass(frozen=True)
class ScannerConfig:
    """Runtime filters used before a pool can become a candidate."""

    min_apr: float = 999.99
    apr_field: str = "apr24h"
    page_size: int = 100
    pages: int = 1
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
    survival_runway: SurvivalRunwayConfig = field(default_factory=SurvivalRunwayConfig)
    quote_only_entry: QuoteOnlyEntryConfig = field(default_factory=QuoteOnlyEntryConfig)
    honeypot_guard: HoneypotGuardConfig = field(default_factory=HoneypotGuardConfig)

    @classmethod
    def from_file(cls, path: Path) -> "ScannerConfig":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        env_urls = split_env_list(os.environ.get("SOLANA_RPC_URLS", ""))
        single_env_url = os.environ.get("SOLANA_RPC_URL", "").strip()
        if single_env_url:
            env_urls.insert(0, single_env_url)
        config_urls = [str(value).strip() for value in raw.get("solana_rpc_urls", []) if str(value).strip()]
        return cls(
            min_apr=float(raw.get("min_apr", cls.min_apr)),
            apr_field=str(raw.get("apr_field", cls.apr_field)),
            page_size=min(int(raw.get("page_size", cls.page_size)), 1000),
            pages=int(raw.get("pages", cls.pages)),
            pool_type=str(raw.get("pool_type", cls.pool_type)),
            sort_type=str(raw.get("sort_type", cls.sort_type)),
            min_liquidity_usd=float(raw.get("min_liquidity_usd", cls.min_liquidity_usd)),
            min_volume_24h_usd=float(raw.get("min_volume_24h_usd", cls.min_volume_24h_usd)),
            max_position_usd=float(raw.get("max_position_usd", cls.max_position_usd)),
            allowed_quote_symbols=set(
                map(str.upper, raw.get("allowed_quote_symbols", ["SOL", "USDC", "USDT", "USD1"]))
            ),
            blocked_token_symbols=set(map(str.upper, raw.get("blocked_token_symbols", []))),
            blocked_mints=set(raw.get("blocked_mints", [])),
            require_pool_id=bool(raw.get("require_pool_id", True)),
            dry_run=bool(raw.get("dry_run", True)),
            raydium_api_base=str(raw.get("raydium_api_base") or os.environ.get("RAYDIUM_API_BASE") or RAYDIUM_API_BASE),
            solana_rpc_urls=dedupe([*env_urls, *config_urls]),
            survival_runway=SurvivalRunwayConfig.from_raw(raw.get("survival_runway")),
            quote_only_entry=QuoteOnlyEntryConfig.from_raw(raw.get("quote_only_entry")),
            honeypot_guard=HoneypotGuardConfig.from_raw(raw.get("honeypot_guard")),
        )


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
    for line in path.read_text(encoding="utf-8-sig").splitlines():
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
        return str(token.get("symbol") or token.get("name") or "").upper()
    return ""


def token_mint(token: Any) -> str:
    if isinstance(token, dict):
        return str(token.get("address") or token.get("mint") or token.get("id") or "")
    return ""


def apr_field_window(apr_field: str) -> str:
    """Map an apr_field name to the Raydium response window dict key.

    Raydium's `/pools/info/list` payload now reports APR (and matching volume/fees)
    inside nested `day`, `week`, and `month` objects, not as flat top-level numbers.
    """

    name = apr_field.lower()
    if "week" in name:
        return "week"
    if "month" in name:
        return "month"
    return "day"


def pool_apr(pool: dict[str, Any], apr_field: str) -> float:
    """Read APR across Raydium response shapes (flat or nested `day`/`week`/`month`)."""

    direct = number(pool.get(apr_field), default=-1.0)
    if direct >= 0:
        return direct

    window = apr_field_window(apr_field)
    window_obj = pool.get(window)
    if isinstance(window_obj, dict):
        for key in ("apr", "feeApr"):
            value = number(window_obj.get(key), default=-1.0)
            if value >= 0:
                return value

    suffix = apr_field.removeprefix("apr")
    apr_obj = pool.get("apr")
    if isinstance(apr_obj, dict):
        for key in (suffix, apr_field, suffix.lower()):
            value = number(apr_obj.get(key), default=-1.0)
            if value >= 0:
                return value

    return 0.0


def pool_volume(pool: dict[str, Any], apr_field: str) -> float:
    """Read 24h-window volume across flat and nested Raydium shapes."""

    for key in ("volume24hUsd", "volume24h"):
        direct = number(pool.get(key), default=-1.0)
        if direct >= 0:
            return direct
    window_obj = pool.get(apr_field_window(apr_field))
    if isinstance(window_obj, dict):
        return number(window_obj.get("volume"), default=0.0)
    return 0.0


def pool_fee(pool: dict[str, Any], apr_field: str) -> float:
    """Read 24h-window fees across flat and nested Raydium shapes."""

    for key in ("fee24hUsd", "fee24h"):
        direct = number(pool.get(key), default=-1.0)
        if direct >= 0:
            return direct
    window_obj = pool.get(apr_field_window(apr_field))
    if isinstance(window_obj, dict):
        return number(window_obj.get("volumeFee"), default=0.0)
    return 0.0


def normalize_pool(pool: dict[str, Any], apr_field: str) -> dict[str, Any]:
    mint_a = nested_get(pool, "mintA", "mint1", "baseMint", default={})
    mint_b = nested_get(pool, "mintB", "mint2", "quoteMint", default={})
    return {
        "id": str(nested_get(pool, "id", "poolId", "ammId", default="")),
        "type": str(nested_get(pool, "type", "poolType", default="")),
        "apr": pool_apr(pool, apr_field),
        "liquidity_usd": number(nested_get(pool, "tvl", "liquidity", "liquidityUsd", default=0)),
        "volume_24h_usd": pool_volume(pool, apr_field),
        "fee_24h_usd": pool_fee(pool, apr_field),
        "mint_a_symbol": token_symbol(mint_a),
        "mint_b_symbol": token_symbol(mint_b),
        "mint_a": token_mint(mint_a),
        "mint_b": token_mint(mint_b),
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


def fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    request = Request(url, headers={"accept": "application/json", "user-agent": "Raydium-LP1/0.2"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - intentional public API read
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"API returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"API request failed for {url}: {reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"API request timed out for {url}") from exc
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


REASON_CATEGORIES: tuple[str, ...] = (
    "missing_pool_id",
    "apr_below_threshold",
    "liquidity_below_threshold",
    "volume_below_threshold",
    "quote_symbol_not_allowed",
    "blocked_symbol",
    "blocked_mint",
    "survival_runway_failed",
    "quote_only_entry_failed",
    "honeypot_guard_failed",
)


def filter_pool(pool: dict[str, Any], config: ScannerConfig) -> tuple[bool, list[str], list[str]]:
    """Return (passed, human_reasons, reason_categories).

    The categories are stable, machine-readable strings so the printable report can
    summarize how many pools failed for each kind of reason without re-parsing the
    free-form text.
    """

    reasons: list[str] = []
    categories: list[str] = []
    if config.require_pool_id and not pool["id"]:
        reasons.append("missing pool id")
        categories.append("missing_pool_id")
    if pool["apr"] < config.min_apr:
        reasons.append(f"apr {pool['apr']:.2f} below {config.min_apr:.2f}")
        categories.append("apr_below_threshold")
    if pool["liquidity_usd"] < config.min_liquidity_usd:
        reasons.append(f"liquidity ${pool['liquidity_usd']:.2f} below ${config.min_liquidity_usd:.2f}")
        categories.append("liquidity_below_threshold")
    if pool["volume_24h_usd"] < config.min_volume_24h_usd:
        reasons.append(f"24h volume ${pool['volume_24h_usd']:.2f} below ${config.min_volume_24h_usd:.2f}")
        categories.append("volume_below_threshold")

    symbols = {pool["mint_a_symbol"], pool["mint_b_symbol"]} - {""}
    if config.allowed_quote_symbols and symbols.isdisjoint(config.allowed_quote_symbols):
        reasons.append(f"no allowed quote symbol in {sorted(symbols)}")
        categories.append("quote_symbol_not_allowed")
    blocked_symbols = symbols.intersection(config.blocked_token_symbols)
    if blocked_symbols:
        reasons.append(f"blocked symbol(s): {', '.join(sorted(blocked_symbols))}")
        categories.append("blocked_symbol")

    mints = {pool["mint_a"], pool["mint_b"]} - {""}
    blocked_mints = mints.intersection(config.blocked_mints)
    if blocked_mints:
        reasons.append(f"blocked mint(s): {', '.join(sorted(blocked_mints))}")
        categories.append("blocked_mint")

    qoe_ok, qoe_reason = evaluate_quote_only_entry(pool, config.quote_only_entry)
    if not qoe_ok and qoe_reason is not None:
        reasons.append(f"quote_only_entry: {qoe_reason}")
        categories.append("quote_only_entry_failed")

    sr_ok, sr_reason = evaluate_survival_runway(pool, config.survival_runway, config.max_position_usd)
    if not sr_ok and sr_reason is not None:
        reasons.append(f"survival_runway: {sr_reason}")
        categories.append("survival_runway_failed")

    return not reasons, reasons, categories


def scan(config: ScannerConfig) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    all_pools: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {key: 0 for key in REASON_CATEGORIES}
    scanned = 0

    for page in range(1, config.pages + 1):
        url = pool_list_url(config, page=page)
        response = fetch_json(url)
        items = extract_pool_items(response)
        for item in items:
            scanned += 1
            # Keep raw payload attached for survival_runway's weekly check.
            pool = normalize_pool(item, config.apr_field)
            ok, reasons, categories = filter_pool(pool, config)
            public_pool = {key: value for key, value in pool.items() if key != "raw"}
            all_pools.append(public_pool)
            if ok:
                # Keep raw payload only while honeypot_guard might still need it.
                candidates.append({**public_pool, "_raw": pool["raw"]})
            else:
                rejected.append({**public_pool, "reasons": reasons, "reason_categories": categories})
                for category in categories:
                    reason_counts[category] = reason_counts.get(category, 0) + 1

    honeypot_inspections: dict[str, dict[str, Any]] = {}
    final_candidates: list[dict[str, Any]] = []
    if config.honeypot_guard.enabled and candidates:
        cache: dict[str, MintInspection | None] = {}
        for candidate in candidates:
            mint_address, _base_symbol = (
                base_side(candidate, config.quote_only_entry) or ("", "")
            )
            ok, reason, inspection = evaluate_honeypot_guard(
                mint_address,
                config.honeypot_guard,
                config.solana_rpc_urls,
                cache=cache,
            )
            candidate.pop("_raw", None)
            if inspection is not None:
                honeypot_inspections[mint_address] = {
                    "owner_program": inspection.owner_program,
                    "is_token_2022": inspection.is_token_2022,
                    "sell_tax_percent": inspection.sell_tax_percent,
                    "freeze_authority_set": inspection.freeze_authority_set,
                    "has_transfer_hook": inspection.has_transfer_hook,
                    "has_permanent_delegate": inspection.has_permanent_delegate,
                }
                candidate["honeypot_inspection"] = honeypot_inspections[mint_address]
            if ok:
                final_candidates.append(candidate)
            else:
                candidate["reasons"] = [f"honeypot_guard: {reason}"]
                candidate["reason_categories"] = ["honeypot_guard_failed"]
                rejected.append(candidate)
                reason_counts["honeypot_guard_failed"] += 1
    else:
        for candidate in candidates:
            candidate.pop("_raw", None)
            final_candidates.append(candidate)

    top_by_apr = sorted(all_pools, key=lambda p: p["apr"], reverse=True)[:5]

    return {
        "scanned_at": datetime.now(UTC).isoformat(),
        "mode": "dry_run" if config.dry_run else "trade_disabled_in_this_build",
        "raydium_api_base": config.raydium_api_base,
        "min_apr": config.min_apr,
        "min_liquidity_usd": config.min_liquidity_usd,
        "min_volume_24h_usd": config.min_volume_24h_usd,
        "apr_field": config.apr_field,
        "scanned_count": scanned,
        "candidate_count": len(final_candidates),
        "rejected_count": len(rejected),
        "rejection_reason_counts": reason_counts,
        "max_position_usd": config.max_position_usd,
        "rpc_count": len(config.solana_rpc_urls),
        "active_filters": {
            "survival_runway": {
                "enabled": config.survival_runway.enabled,
                "target_survival_days": config.survival_runway.target_survival_days,
                "min_tvl_multiple_of_position": config.survival_runway.min_tvl_multiple_of_position,
                "min_daily_volume_pct_of_tvl": config.survival_runway.min_daily_volume_pct_of_tvl,
            },
            "quote_only_entry": {
                "enabled": config.quote_only_entry.enabled,
                "allowed_quote_symbols": sorted(config.quote_only_entry.allowed_quote_symbols),
                "require_concentrated_pool": config.quote_only_entry.require_concentrated_pool,
            },
            "honeypot_guard": {
                "enabled": config.honeypot_guard.enabled,
                "max_sell_tax_percent": config.honeypot_guard.max_sell_tax_percent,
                "reject_if_freeze_authority_set": config.honeypot_guard.reject_if_freeze_authority_set,
                "reject_if_transfer_hook_set": config.honeypot_guard.reject_if_transfer_hook_set,
                "reject_if_permanent_delegate_set": config.honeypot_guard.reject_if_permanent_delegate_set,
                "fail_open_when_no_rpc": config.honeypot_guard.fail_open_when_no_rpc,
            },
        },
        "candidates": final_candidates,
        "top_by_apr": top_by_apr,
        "rejected_preview": rejected[:10],
    }


def _format_pool_line(pool: dict[str, Any]) -> str:
    pair = f"{pool['mint_a_symbol'] or '?'}/{pool['mint_b_symbol'] or '?'}"
    return (
        f"- {pair} | APR {pool['apr']:.2f}% | TVL ${pool['liquidity_usd']:.2f} | "
        f"24h Vol ${pool['volume_24h_usd']:.2f} | Pool {pool['id']}"
    )


def print_report(report: dict[str, Any]) -> None:
    print("Raydium-LP1 live scan")
    print(f"Time: {report['scanned_at']}")
    print(f"Mode: {report['mode']}")
    print(f"APR filter: {report['apr_field']} >= {report['min_apr']:.2f}%")
    print(f"Liquidity filter: TVL >= ${report.get('min_liquidity_usd', 0):.2f}")
    print(f"Volume filter:   24h vol >= ${report.get('min_volume_24h_usd', 0):.2f}")
    print(f"Scanned: {report['scanned_count']} | Candidates: {report['candidate_count']} | Rejected: {report['rejected_count']}")
    print(f"Configured Solana RPCs: {report['rpc_count']}")
    print(f"Max future position size: ${report['max_position_usd']:.2f}")

    active = report.get("active_filters") or {}
    sr = active.get("survival_runway") or {}
    qoe = active.get("quote_only_entry") or {}
    hg = active.get("honeypot_guard") or {}
    if sr.get("enabled"):
        print(
            f"Survival runway: target {sr.get('target_survival_days')}d, "
            f"min TVL {sr.get('min_tvl_multiple_of_position')}x position, "
            f"min daily vol/TVL {sr.get('min_daily_volume_pct_of_tvl')}%"
        )
    if qoe.get("enabled"):
        symbols = ", ".join(qoe.get("allowed_quote_symbols", []))
        print(f"Quote-only entry: allowed quotes = {symbols}")
    if hg.get("enabled"):
        print(
            f"Honeypot guard: max sell tax {hg.get('max_sell_tax_percent')}%, "
            f"freeze-reject={hg.get('reject_if_freeze_authority_set')}, "
            f"hook-reject={hg.get('reject_if_transfer_hook_set')}, "
            f"perm-delegate-reject={hg.get('reject_if_permanent_delegate_set')}"
        )

    if report["candidates"]:
        print("\nCandidates:")
        for pool in report["candidates"]:
            print(_format_pool_line(pool))
            inspection = pool.get("honeypot_inspection")
            if inspection:
                print(
                    "    HoneypotGuard: token-2022="
                    f"{inspection['is_token_2022']} sell_tax={inspection['sell_tax_percent']:.2f}% "
                    f"freeze={inspection['freeze_authority_set']} "
                    f"hook={inspection['has_transfer_hook']} "
                    f"perm_delegate={inspection['has_permanent_delegate']}"
                )
        print("\nDry-run only: no buy, no wallet signing, no LP position opened.")
        return

    print("\nNo pools passed all filters. No action taken.")

    reason_counts = report.get("rejection_reason_counts") or {}
    nonzero = [(name, count) for name, count in reason_counts.items() if count]
    if nonzero:
        print("\nWhy pools were rejected (a pool can fail more than one filter):")
        for name, count in sorted(nonzero, key=lambda item: item[1], reverse=True):
            print(f"  - {name}: {count}")

    top_by_apr = report.get("top_by_apr") or []
    if top_by_apr:
        print("\nTop 5 pools by APR in this scan (for tuning your thresholds):")
        for pool in top_by_apr:
            print(_format_pool_line(pool))
        print(
            "\nTip: if everything failed `liquidity_below_threshold` or `volume_below_threshold`, "
            "those pools are too tiny to enter safely. Lower `min_apr` or raise `pages` in "
            "config\\settings.json to widen the search."
        )


def write_reports(report: dict[str, Any], reports_dir: Path = REPORTS_DIR) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    latest_json = reports_dir / "latest.json"
    stamped_json = reports_dir / f"scan-{timestamp}.json"
    latest_csv = reports_dir / "candidates.csv"
    payload = json.dumps(report, indent=2, sort_keys=True)
    latest_json.write_text(payload + "\n", encoding="utf-8")
    stamped_json.write_text(payload + "\n", encoding="utf-8")
    with latest_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["scanned_at", "pool_id", "pair", "apr", "liquidity_usd", "volume_24h_usd", "decision"],
        )
        writer.writeheader()
        for pool in report["candidates"]:
            writer.writerow(
                {
                    "scanned_at": report["scanned_at"],
                    "pool_id": pool["id"],
                    "pair": f"{pool['mint_a_symbol']}/{pool['mint_b_symbol']}",
                    "apr": pool["apr"],
                    "liquidity_usd": pool["liquidity_usd"],
                    "volume_24h_usd": pool["volume_24h_usd"],
                    "decision": "WATCH_ONLY_DRY_RUN",
                }
            )


def resolve_config_path(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_CONFIG_PATH and FALLBACK_CONFIG_PATH.exists():
        return FALLBACK_CONFIG_PATH
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan live Raydium LPs for extreme APR candidates.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to scanner JSON config.")
    parser.add_argument("--json", action="store_true", help="Print the scan report as JSON.")
    parser.add_argument("--loop", action="store_true", help="Keep scanning until stopped.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between scans in loop mode.")
    parser.add_argument("--write-reports", action="store_true", help="Write reports/latest.json and reports/candidates.csv.")
    parser.add_argument("--check-rpc", action="store_true", help="Check configured Solana RPC URLs with getHealth before scanning.")
    args = parser.parse_args(argv)

    load_dotenv()
    config_path = resolve_config_path(args.config)
    config = ScannerConfig.from_file(config_path)
    if not config.dry_run:
        print("Refusing to run: this build is dry-run only. Set dry_run=true.", file=sys.stderr)
        return 2

    if args.check_rpc:
        rpc_results = check_rpc_urls(config.solana_rpc_urls)
        print(json.dumps({"rpc_results": rpc_results}, indent=2))

    while True:
        try:
            report = scan(config)
        except RuntimeError as exc:
            print(f"Scan failed: {exc}", file=sys.stderr)
            return 1

        if args.write_reports:
            write_reports(report)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print_report(report)
        if not args.loop:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
