"""Sellability / route checks for Raydium-LP1.

Before any pool can become a candidate the scanner needs to confirm that the
two underlying tokens can actually be sold back into a base asset (SOL,
USDC, or USDT). This module talks to Jupiter v6's quote API and to Raydium's
own swap API as a secondary source and aggregates the results.

Everything in here is read-only public API access. No trades are signed.
Feature 9 (``robust_routes.py``) extends this module with caching and extra
route sources (Orca, Raydium AMM direct).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
RAYDIUM_COMPUTE_URL = "https://transaction-v1.raydium.io/compute/swap-base-in"

WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB"

# Default sell amount we probe with: 0.1 token (10**6 base units for tokens with
# 6 decimals; this is just a smoke test, the API accepts any positive amount).
DEFAULT_PROBE_AMOUNT = 100_000  # ~0.1 of a 6-decimal token

BASE_TOKENS: dict[str, str] = {
    "SOL": WSOL_MINT,
    "WSOL": WSOL_MINT,
    "USDC": USDC_MINT,
    "USDT": USDT_MINT,
}


@dataclass(frozen=True)
class RouteCheck:
    """A single sell-route probe result.

    ``ok`` is True when at least one priced route was returned from any
    source. ``sources`` is the per-provider breakdown for logging.
    """

    token_mint: str
    token_symbol: str
    target_mint: str
    target_symbol: str
    ok: bool
    sources: list[dict[str, object]] = field(default_factory=list)
    best_price: float | None = None
    best_source: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "token_mint": self.token_mint,
            "token_symbol": self.token_symbol,
            "target_mint": self.target_mint,
            "target_symbol": self.target_symbol,
            "ok": self.ok,
            "best_price": self.best_price,
            "best_source": self.best_source,
            "sources": list(self.sources),
        }


HttpFetcher = Callable[[str], dict]


def _default_fetch_json(url: str, timeout: int = 8) -> dict:
    request = Request(
        url,
        headers={"accept": "application/json", "user-agent": "Raydium-LP1/0.3"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - public API
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc


def _truthy_route(payload: object) -> bool:
    """Return True if a quote payload looks like a real priced route."""

    if isinstance(payload, dict):
        if payload.get("error") or payload.get("errorCode"):
            return False
        data = payload.get("data") or payload
        if isinstance(data, dict):
            if data.get("outAmount") or data.get("outputAmount") or data.get("outAmountWithSlippage"):
                return True
            if data.get("routePlan") or data.get("routes"):
                return True
        if isinstance(data, list) and data:
            return True
        if payload.get("outAmount") or payload.get("routePlan"):
            return True
    return False


def _extract_out_amount(payload: dict) -> float | None:
    """Best-effort: pull an outAmount-like number for ranking sources."""

    candidates: list[object] = []
    if isinstance(payload, dict):
        candidates.extend([payload.get("outAmount"), payload.get("outputAmount")])
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.extend([data.get("outAmount"), data.get("outputAmount")])
        elif isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                candidates.extend([first.get("outAmount"), first.get("outputAmount")])
    for value in candidates:
        try:
            if value is None:
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def check_jupiter_route(
    token_mint: str,
    target_mint: str,
    *,
    amount: int = DEFAULT_PROBE_AMOUNT,
    slippage_bps: int = 3000,
    fetcher: HttpFetcher | None = None,
) -> dict[str, object]:
    """Probe Jupiter v6 ``/quote`` for ``token_mint -> target_mint``."""

    fetch = fetcher or _default_fetch_json
    params = {
        "inputMint": token_mint,
        "outputMint": target_mint,
        "amount": amount,
        "slippageBps": slippage_bps,
        "onlyDirectRoutes": "false",
        "swapMode": "ExactIn",
    }
    url = f"{JUPITER_QUOTE_URL}?{urlencode(params)}"
    try:
        payload = fetch(url)
    except RuntimeError as exc:
        return {"source": "jupiter", "ok": False, "error": str(exc), "url": url}
    ok = _truthy_route(payload)
    return {
        "source": "jupiter",
        "ok": ok,
        "out_amount": _extract_out_amount(payload),
        "url": url,
    }


def check_raydium_route(
    token_mint: str,
    target_mint: str,
    *,
    amount: int = DEFAULT_PROBE_AMOUNT,
    slippage_bps: int = 3000,
    fetcher: HttpFetcher | None = None,
) -> dict[str, object]:
    """Probe Raydium's swap-quote API for ``token_mint -> target_mint``."""

    fetch = fetcher or _default_fetch_json
    params = {
        "inputMint": token_mint,
        "outputMint": target_mint,
        "amount": amount,
        "slippageBps": slippage_bps,
        "txVersion": "V0",
    }
    url = f"{RAYDIUM_COMPUTE_URL}?{urlencode(params)}"
    try:
        payload = fetch(url)
    except RuntimeError as exc:
        return {"source": "raydium", "ok": False, "error": str(exc), "url": url}
    ok = _truthy_route(payload)
    return {
        "source": "raydium",
        "ok": ok,
        "out_amount": _extract_out_amount(payload),
        "url": url,
    }


ROUTE_SOURCES: dict[str, Callable[..., dict[str, object]]] = {
    "jupiter": check_jupiter_route,
    "raydium": check_raydium_route,
}


def check_sell_route(
    token_mint: str,
    token_symbol: str,
    *,
    base_symbols: Sequence[str] = ("SOL", "USDC", "USDT"),
    sources: Iterable[str] = ("jupiter", "raydium"),
    fetcher: HttpFetcher | None = None,
) -> RouteCheck:
    """Try every base + every source until we find a priced route.

    The first ``(source, base)`` combination that returns a usable route
    wins. We still record per-source results in ``sources`` for the log.
    """

    token_symbol_upper = (token_symbol or "").upper()
    if token_symbol_upper in BASE_TOKENS:
        # Base tokens are trivially sellable.
        return RouteCheck(
            token_mint=token_mint,
            token_symbol=token_symbol_upper,
            target_mint=BASE_TOKENS[token_symbol_upper],
            target_symbol=token_symbol_upper,
            ok=True,
            sources=[{"source": "base-token", "ok": True}],
            best_price=1.0,
            best_source="base-token",
        )

    if not token_mint:
        return RouteCheck(
            token_mint="",
            token_symbol=token_symbol_upper,
            target_mint="",
            target_symbol="",
            ok=False,
            sources=[{"source": "n/a", "ok": False, "error": "missing token mint"}],
        )

    records: list[dict[str, object]] = []
    best_record: dict[str, object] | None = None
    best_target_symbol = ""
    best_target_mint = ""
    for base_symbol in base_symbols:
        target_mint = BASE_TOKENS.get(base_symbol.upper())
        if not target_mint or target_mint == token_mint:
            continue
        for source_name in sources:
            checker = ROUTE_SOURCES.get(source_name)
            if checker is None:
                continue
            record = checker(token_mint, target_mint, fetcher=fetcher)
            record["target_symbol"] = base_symbol.upper()
            records.append(record)
            if record.get("ok") and (
                best_record is None
                or (record.get("out_amount") or 0) > (best_record.get("out_amount") or 0)
            ):
                best_record = record
                best_target_symbol = base_symbol.upper()
                best_target_mint = target_mint
    ok = best_record is not None
    return RouteCheck(
        token_mint=token_mint,
        token_symbol=token_symbol_upper,
        target_mint=best_target_mint,
        target_symbol=best_target_symbol,
        ok=ok,
        sources=records,
        best_price=float(best_record.get("out_amount")) if best_record and best_record.get("out_amount") is not None else None,
        best_source=str(best_record.get("source")) if best_record else None,
    )


@dataclass(frozen=True)
class SellabilityResult:
    """Aggregate sellability verdict for a pool's two tokens."""

    ok: bool
    reasons: list[str]
    token_a: RouteCheck
    token_b: RouteCheck

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "reasons": list(self.reasons),
            "token_a": self.token_a.to_dict(),
            "token_b": self.token_b.to_dict(),
        }


def check_pool_sellability(
    pool: dict,
    *,
    base_symbols: Sequence[str] = ("SOL", "USDC", "USDT"),
    sources: Iterable[str] = ("jupiter", "raydium"),
    fetcher: HttpFetcher | None = None,
) -> SellabilityResult:
    """Run :func:`check_sell_route` for both tokens in a normalized pool."""

    token_a = check_sell_route(
        pool.get("mint_a", ""),
        pool.get("mint_a_symbol", ""),
        base_symbols=base_symbols,
        sources=sources,
        fetcher=fetcher,
    )
    token_b = check_sell_route(
        pool.get("mint_b", ""),
        pool.get("mint_b_symbol", ""),
        base_symbols=base_symbols,
        sources=sources,
        fetcher=fetcher,
    )
    reasons: list[str] = []
    if not token_a.ok:
        reasons.append(f"no sell route for token A ({token_a.token_symbol or token_a.token_mint[:8]})")
    if not token_b.ok:
        reasons.append(f"no sell route for token B ({token_b.token_symbol or token_b.token_mint[:8]})")
    return SellabilityResult(
        ok=not reasons,
        reasons=reasons,
        token_a=token_a,
        token_b=token_b,
    )


def format_sellability_log(result: SellabilityResult) -> str:
    """Compact one-line log entry: which sources were checked and the verdict."""

    def per_token(check: RouteCheck) -> str:
        if not check.sources:
            return f"{check.token_symbol or check.token_mint[:6]}: no sources"
        parts = []
        for record in check.sources:
            mark = "OK" if record.get("ok") else "X"
            src = record.get("source", "?")
            tgt = record.get("target_symbol") or ""
            parts.append(f"{src}->{tgt}:{mark}" if tgt else f"{src}:{mark}")
        verdict = "OK" if check.ok else "BLOCK"
        return f"{check.token_symbol or check.token_mint[:6]}={verdict}[{', '.join(parts)}]"

    return f"sellability: {per_token(result.token_a)} | {per_token(result.token_b)}"
