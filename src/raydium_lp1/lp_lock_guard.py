"""LpLockGuard: refuse pools whose LP supply isn't burned or locked.

The name to remember is **lp_lock_guard**.

What it asks, in plain English:
- After a launch, who can pull liquidity out of this Raydium pool? If the
  pool's creator still holds the LP tokens, they can withdraw the whole
  pool in one transaction (the classic "soft rug"). The defense is to
  require that a high fraction of LP supply was burned (sent to the
  incinerator address) or moved to a known LP-locker program.
- This guard makes a best-effort estimate from on-chain data we can read
  without indexing every wallet: the LP mint supply minus the total
  vested/circulating LP that we can identify, expressed as a percentage.
  When that percentage clears `min_locked_or_burned_pct`, the pool passes.

Sources we use:
1. The Raydium snapshot already includes the LP mint address (`lpMint`) and
   sometimes a hint about LP burn (`burnPercent`, `lpAmount`). When the
   snapshot includes those fields we trust them.
2. If we have a Solana JSON-RPC, we ask for the LP mint's `supply` and
   compare to the LP balance at the well-known incinerator address
   (`1nc1nerator11111111111111111111111111111111`). The fraction held by
   the incinerator counts toward the lock total.
3. Concentrated/CLMM pools use NFT positions instead of fungible LP tokens.
   For CLMM pools this filter accepts by default unless the operator turns
   on `apply_to_concentrated_pools`.

Behavior on missing/failed RPC matches `honeypot_guard`:
- `fail_open_when_no_rpc=False` (default for CPMM/AMM pools) -> fails closed.
- `fail_open_when_no_rpc=True`                                -> skip & accept.

Settings live under `lp_lock_guard` in `config/settings.json`. See SETTINGS.md.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

INCINERATOR_ADDRESS = "1nc1nerator11111111111111111111111111111111"


@dataclass(frozen=True)
class LpLockGuardConfig:
    enabled: bool = True
    min_locked_or_burned_pct: float = 90.0
    apply_to_concentrated_pools: bool = False
    fail_open_when_no_rpc: bool = False
    rpc_timeout_seconds: float = 8.0

    @classmethod
    def from_raw(cls, raw: Any) -> "LpLockGuardConfig":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            min_locked_or_burned_pct=float(
                raw.get("min_locked_or_burned_pct", cls.min_locked_or_burned_pct)
            ),
            apply_to_concentrated_pools=bool(
                raw.get("apply_to_concentrated_pools", cls.apply_to_concentrated_pools)
            ),
            fail_open_when_no_rpc=bool(raw.get("fail_open_when_no_rpc", cls.fail_open_when_no_rpc)),
            rpc_timeout_seconds=float(raw.get("rpc_timeout_seconds", cls.rpc_timeout_seconds)),
        )


@dataclass(frozen=True)
class LpLockInspection:
    lp_mint: str
    burned_pct: float
    source: str


def _is_concentrated(pool: dict[str, Any]) -> bool:
    pool_type = (pool.get("type") or "").lower()
    return "concentrated" in pool_type or "clmm" in pool_type


def _extract_burn_hint(raw: Any) -> float | None:
    """Some Raydium payloads include a `burnPercent` or similar field."""

    if not isinstance(raw, dict):
        return None
    for key in ("burnPercent", "burn_percent", "lpBurnPercent", "lpBurn"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 1.0:
            return number
        return number * 100.0
    return None


def _extract_lp_mint(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    for key in ("lpMint", "lpMintAddress", "lp_mint"):
        value = raw.get(key)
        if isinstance(value, dict):
            address = value.get("address") or value.get("mint") or value.get("id")
            if address:
                return str(address)
        elif isinstance(value, str) and value:
            return value
    return ""


def _post_rpc(rpc_url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    request = Request(
        rpc_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "Raydium-LP1/0.4 LpLockGuard",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured RPC
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def _get_token_supply(rpc_url: str, lp_mint: str, timeout: float) -> int | None:
    body = _post_rpc(
        rpc_url,
        {"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [lp_mint]},
        timeout=timeout,
    )
    value = ((body or {}).get("result") or {}).get("value") or {}
    amount = value.get("amount")
    if amount is None:
        return None
    try:
        return int(amount)
    except (TypeError, ValueError):
        return None


def _get_incinerator_lp_balance(rpc_url: str, lp_mint: str, timeout: float) -> int | None:
    body = _post_rpc(
        rpc_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                INCINERATOR_ADDRESS,
                {"mint": lp_mint},
                {"encoding": "base64"},
            ],
        },
        timeout=timeout,
    )
    if body is None:
        return None
    accounts = ((body or {}).get("result") or {}).get("value") or []
    total = 0
    if not accounts:
        return 0
    for entry in accounts:
        data_field = (entry or {}).get("account", {}).get("data")
        if not isinstance(data_field, list) or not data_field:
            continue
        try:
            raw_bytes = base64.b64decode(data_field[0])
        except (TypeError, ValueError):
            continue
        if len(raw_bytes) < 72:
            continue
        amount = int.from_bytes(raw_bytes[64:72], "little", signed=False)
        total += amount
    return total


def inspect_lp_lock(
    pool: dict[str, Any],
    config: LpLockGuardConfig,
    rpc_urls: list[str],
    cache: dict[str, LpLockInspection | None] | None = None,
) -> LpLockInspection | None:
    """Best-effort estimate of the LP burn/lock percentage."""

    raw = pool.get("raw")
    lp_mint = _extract_lp_mint(raw)
    if not lp_mint:
        return None
    if cache is not None and lp_mint in cache:
        return cache[lp_mint]

    hint = _extract_burn_hint(raw)
    inspection: LpLockInspection | None = None
    if hint is not None:
        inspection = LpLockInspection(lp_mint=lp_mint, burned_pct=hint, source="raydium_snapshot")

    if inspection is None:
        for rpc_url in rpc_urls:
            supply = _get_token_supply(rpc_url, lp_mint, timeout=config.rpc_timeout_seconds)
            if supply is None:
                continue
            burned = _get_incinerator_lp_balance(rpc_url, lp_mint, timeout=config.rpc_timeout_seconds)
            if burned is None:
                continue
            pct = (burned / supply) * 100.0 if supply > 0 else 100.0
            inspection = LpLockInspection(
                lp_mint=lp_mint, burned_pct=pct, source="rpc_incinerator_balance"
            )
            break

    if cache is not None:
        cache[lp_mint] = inspection
    return inspection


def evaluate_lp_lock_guard(
    pool: dict[str, Any],
    inspection: LpLockInspection | None,
    config: LpLockGuardConfig,
    *,
    has_rpc_configured: bool,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails) for the LP-lock check."""

    if not config.enabled:
        return True, None

    if _is_concentrated(pool) and not config.apply_to_concentrated_pools:
        return True, None

    if inspection is None:
        if not has_rpc_configured:
            if config.fail_open_when_no_rpc:
                return True, None
            return False, (
                "no Solana RPC configured; lp_lock_guard cannot read LP mint supply"
            )
        if config.fail_open_when_no_rpc:
            return True, None
        return False, "could not read LP mint supply; lp_lock_guard fails closed"

    if inspection.burned_pct < config.min_locked_or_burned_pct:
        return False, (
            f"LP burn/lock {inspection.burned_pct:.2f}% below required "
            f"{config.min_locked_or_burned_pct:.2f}% (creator can still pull liquidity)"
        )

    return True, None


__all__ = [
    "INCINERATOR_ADDRESS",
    "LpLockGuardConfig",
    "LpLockInspection",
    "evaluate_lp_lock_guard",
    "inspect_lp_lock",
]
