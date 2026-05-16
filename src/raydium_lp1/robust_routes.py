"""Robust multi-source route finding with caching.

Wraps the basic Jupiter and Raydium probes in :mod:`raydium_lp1.routes` and
adds two more sources (Orca Whirlpool quoting via their public swap-quote
endpoint, and Raydium AMM-direct), plus:

* A per-(input_mint, output_mint) cache with a 5-minute TTL so we don't
  hammer the upstream APIs on every scan.
* Best-price selection across all sources for a single sell decision.
* Quality metrics: how many sources priced, dispersion of out-amounts,
  cache hit/miss counts.

This module is intentionally additive: callers that just want the
"is this pool sellable at all?" check should keep using
:func:`raydium_lp1.routes.check_pool_sellability`. Callers that want a
ranked, cached best-price decision (the emergency closer, future real
swap path, dashboards) should use :func:`best_route` here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from raydium_lp1 import routes
from raydium_lp1.http_json import load_json_from_urlopen_response

ORCA_QUOTE_URL = "https://api.orca.so/v2/solana/swap-quote"
RAYDIUM_AMM_QUOTE_URL = "https://transaction-v1.raydium.io/compute/swap-base-in"
CACHE_TTL_SECONDS = 300  # 5 minutes per spec

HttpFetcher = Callable[[str], dict]


# ---------------------------------------------------------------------------
# Extra route sources
# ---------------------------------------------------------------------------

def _default_fetch_json(url: str, timeout: int = 8) -> dict:
    request = Request(
        url,
        headers={
            "accept": "application/json",
            "accept-encoding": "identity",
            "user-agent": "Raydium-LP1/0.5",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return load_json_from_urlopen_response(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc


def check_orca_route(
    token_mint: str,
    target_mint: str,
    *,
    amount: int = routes.DEFAULT_PROBE_AMOUNT,
    slippage_bps: int = 3000,
    fetcher: HttpFetcher | None = None,
) -> dict[str, object]:
    fetch = fetcher or _default_fetch_json
    params = {
        "inputMint": token_mint,
        "outputMint": target_mint,
        "amount": amount,
        "slippageBps": slippage_bps,
    }
    url = f"{ORCA_QUOTE_URL}?{urlencode(params)}"
    try:
        payload = fetch(url)
    except RuntimeError as exc:
        return {"source": "orca", "ok": False, "error": str(exc), "url": url}
    ok = routes._truthy_route(payload)
    return {
        "source": "orca",
        "ok": ok,
        "out_amount": routes._extract_out_amount(payload),
        "url": url,
    }


def check_raydium_amm_route(
    token_mint: str,
    target_mint: str,
    *,
    amount: int = routes.DEFAULT_PROBE_AMOUNT,
    slippage_bps: int = 3000,
    fetcher: HttpFetcher | None = None,
) -> dict[str, object]:
    """Direct Raydium AMM quote (uses the same compute endpoint with txVersion=V0)."""

    fetch = fetcher or _default_fetch_json
    params = {
        "inputMint": token_mint,
        "outputMint": target_mint,
        "amount": amount,
        "slippageBps": slippage_bps,
        "txVersion": "V0",
        "swapType": "BaseIn",
    }
    url = f"{RAYDIUM_AMM_QUOTE_URL}?{urlencode(params)}"
    try:
        payload = fetch(url)
    except RuntimeError as exc:
        return {"source": "raydium_amm", "ok": False, "error": str(exc), "url": url}
    ok = routes._truthy_route(payload)
    return {
        "source": "raydium_amm",
        "ok": ok,
        "out_amount": routes._extract_out_amount(payload),
        "url": url,
    }


EXTENDED_SOURCES: dict[str, Callable[..., dict[str, object]]] = {
    "jupiter": routes.check_jupiter_route,
    "raydium": routes.check_raydium_route,
    "orca": check_orca_route,
    "raydium_amm": check_raydium_amm_route,
}

# Default order = priority for tie-breaking when out_amount matches.
DEFAULT_SOURCE_ORDER = ("jupiter", "raydium", "orca", "raydium_amm")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    ts: float
    value: dict


@dataclass
class RouteCache:
    """Simple in-memory cache keyed by (input_mint, output_mint, source).

    Time source is injectable so tests can move the clock forward without
    sleeping.
    """

    ttl_seconds: int = CACHE_TTL_SECONDS
    _store: dict[tuple[str, str, str], _CacheEntry] = field(default_factory=dict)
    _hits: int = 0
    _misses: int = 0
    _clock: Callable[[], float] = field(default=time.time)

    def get(self, input_mint: str, output_mint: str, source: str) -> dict | None:
        key = (input_mint, output_mint, source)
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        if self._clock() - entry.ts > self.ttl_seconds:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        return dict(entry.value)

    def put(self, input_mint: str, output_mint: str, source: str, value: dict) -> None:
        self._store[(input_mint, output_mint, source)] = _CacheEntry(
            ts=self._clock(), value=dict(value)
        )

    def stats(self) -> dict:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._store),
            "ttl_seconds": self.ttl_seconds,
        }

    def clear(self) -> None:
        self._store.clear()
        self._hits = 0
        self._misses = 0


_GLOBAL_CACHE = RouteCache()


def get_global_cache() -> RouteCache:
    return _GLOBAL_CACHE


# ---------------------------------------------------------------------------
# Best-route picker
# ---------------------------------------------------------------------------

@dataclass
class BestRoute:
    input_mint: str
    output_mint: str
    sources: list[dict]
    best_source: str | None
    best_out_amount: float | None
    quality: dict

    def to_dict(self) -> dict:
        return {
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "sources": list(self.sources),
            "best_source": self.best_source,
            "best_out_amount": self.best_out_amount,
            "quality": dict(self.quality),
        }


def best_route(
    input_mint: str,
    output_mint: str,
    *,
    amount: int = routes.DEFAULT_PROBE_AMOUNT,
    slippage_bps: int = 3000,
    sources: Iterable[str] = DEFAULT_SOURCE_ORDER,
    fetcher: HttpFetcher | None = None,
    cache: RouteCache | None = None,
) -> BestRoute:
    """Probe all enabled sources and return the best-priced route.

    Cache hits are reused within ``cache.ttl_seconds`` (default 5 minutes).
    Each per-source record contains an extra ``cached`` flag for logging.
    """

    cache = cache if cache is not None else _GLOBAL_CACHE
    records: list[dict] = []
    for source_name in sources:
        checker = EXTENDED_SOURCES.get(source_name)
        if checker is None:
            continue
        cached = cache.get(input_mint, output_mint, source_name)
        if cached is not None:
            record = dict(cached)
            record["cached"] = True
            records.append(record)
            continue
        record = checker(
            input_mint,
            output_mint,
            amount=amount,
            slippage_bps=slippage_bps,
            fetcher=fetcher,
        )
        record["cached"] = False
        cache.put(input_mint, output_mint, source_name, record)
        records.append(record)

    priced = [r for r in records if r.get("ok") and r.get("out_amount") is not None]
    best_record: dict | None = None
    for record in priced:
        if best_record is None or float(record["out_amount"]) > float(best_record["out_amount"]):
            best_record = record

    out_amounts = [float(r["out_amount"]) for r in priced]
    quality = {
        "sources_priced": len(priced),
        "sources_attempted": len(records),
        "best_out_amount": float(best_record["out_amount"]) if best_record else None,
        "worst_out_amount": min(out_amounts) if out_amounts else None,
        "dispersion_pct": (
            (max(out_amounts) - min(out_amounts)) / max(out_amounts) * 100
            if out_amounts and max(out_amounts) > 0
            else None
        ),
        "cache_hits": sum(1 for r in records if r.get("cached")),
    }
    return BestRoute(
        input_mint=input_mint,
        output_mint=output_mint,
        sources=records,
        best_source=str(best_record["source"]) if best_record else None,
        best_out_amount=float(best_record["out_amount"]) if best_record else None,
        quality=quality,
    )


def log_route_quality(best: BestRoute) -> str:
    """Compact log line summarizing quality metrics."""

    parts = [
        f"best={best.best_source or 'none'}",
        f"sources_priced={best.quality['sources_priced']}/{best.quality['sources_attempted']}",
        f"cache_hits={best.quality['cache_hits']}",
    ]
    if best.quality.get("dispersion_pct") is not None:
        parts.append(f"dispersion={best.quality['dispersion_pct']:.2f}%")
    return f"route_quality: {' '.join(parts)}"
