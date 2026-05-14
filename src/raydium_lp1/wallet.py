"""Wallet management for Raydium-LP1 (dry-run).

Reads wallet config from ``.env`` (or arbitrary env source) so secrets never
get committed. Provides:

* :class:`WalletConfig` - immutable container for address + (redacted) key.
* :func:`load_wallet` - read env vars and validate.
* :func:`override_wallet` - swap the active wallet without restarting.
* :func:`sell_all_to_base` - dry-run plan that converts every token holding
  back to a base token (SOL by default), without executing.

This module never logs or prints the private key. The private key is held in
memory as a string but redacted in any ``to_dict`` / ``__repr__``.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from raydium_lp1 import emergency

LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_POSITION_SIZE_SOL = 0.1
RPC_TIMEOUT_SECONDS = 8

RpcCaller = Callable[[str, dict], dict]

ENV_WALLET_ADDRESS = "WALLET_ADDRESS"
ENV_WALLET_PRIVATE_KEY = "WALLET_PRIVATE_KEY"

# A Solana public key is 32 bytes base58 encoded -> typically 32-44 chars,
# alphabet {1-9, A-H, J-N, P-Z, a-k, m-z}. We do not validate fully; this is
# a sanity check so we fail loud on obvious typos.
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,88}$")


class WalletError(ValueError):
    """Raised when wallet config is malformed."""


@dataclass(frozen=True)
class WalletConfig:
    address: str
    private_key: str = field(repr=False, default="")
    source: str = "env"

    def has_private_key(self) -> bool:
        return bool(self.private_key)

    def redacted_key(self) -> str:
        if not self.private_key:
            return ""
        head = self.private_key[:4]
        return f"{head}...REDACTED"

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "has_private_key": self.has_private_key(),
            "private_key": self.redacted_key(),
            "source": self.source,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"WalletConfig(address={self.address!r}, source={self.source!r}, private_key=REDACTED)"


def _validate_address(address: str) -> None:
    if not address:
        raise WalletError("wallet address is empty")
    if not _BASE58_RE.match(address):
        raise WalletError(
            f"wallet address does not look like a valid base58 string: {address[:8]}..."
        )


def load_wallet(env: dict[str, str] | None = None, *, required: bool = False) -> WalletConfig | None:
    """Load wallet config from environment variables.

    Returns ``None`` when no address is configured and ``required`` is False.
    Raises :class:`WalletError` if the address is set but malformed, or if
    ``required=True`` and nothing is configured.
    """

    env = env if env is not None else os.environ
    address = (env.get(ENV_WALLET_ADDRESS) or "").strip()
    private_key = (env.get(ENV_WALLET_PRIVATE_KEY) or "").strip()
    if not address:
        if required:
            raise WalletError(
                f"missing {ENV_WALLET_ADDRESS} in environment; set it in .env"
            )
        return None
    _validate_address(address)
    return WalletConfig(address=address, private_key=private_key, source="env")


def override_wallet(address: str, *, private_key: str = "", source: str = "override") -> WalletConfig:
    """Build a fresh :class:`WalletConfig` from caller-supplied values.

    Use this when the user passes ``--wallet-override <address>`` or hits a
    "switch wallet" action mid-run. The new config can be swapped into the
    runtime without restarting the scanner because all consumers take the
    wallet as a parameter (no module-level globals).
    """

    _validate_address(address)
    return WalletConfig(address=address, private_key=private_key, source=source)


@dataclass(frozen=True)
class TokenHolding:
    mint: str
    symbol: str
    amount: int  # base units (e.g. lamports for SOL, raw token units otherwise)
    decimals: int = 6

    def display_amount(self) -> float:
        if self.decimals <= 0:
            return float(self.amount)
        return self.amount / (10 ** self.decimals)


def sell_all_to_base(
    wallet: WalletConfig,
    holdings: Iterable[TokenHolding],
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = 0.30,
) -> dict:
    """Return a dry-run plan that converts every non-base holding to ``base_symbol``.

    Output structure::

        {
          "wallet": "...redacted...",
          "base_symbol": "SOL",
          "dry_run": True,
          "plans": [SwapPlan dict, ...],
          "skipped": [{"symbol": "SOL", "reason": "already base"}, ...],
        }
    """

    plans: list[dict] = []
    skipped: list[dict] = []
    base_upper = base_symbol.upper()
    for holding in holdings:
        if (holding.symbol or "").upper() == base_upper:
            skipped.append({"symbol": holding.symbol, "reason": "already base"})
            continue
        if holding.amount <= 0:
            skipped.append({"symbol": holding.symbol, "reason": "zero balance"})
            continue
        plan = emergency.build_swap_plan(
            holding.mint,
            holding.symbol,
            holding.amount,
            base_symbol=base_upper,
            max_slippage_pct=max_slippage_pct,
        )
        plans.append(plan.to_dict())
    return {
        "wallet": wallet.to_dict(),
        "base_symbol": base_upper,
        "dry_run": True,
        "plans": plans,
        "skipped": skipped,
        "note": "DRY-RUN: no swap was executed. Use this plan as input to real signing once dry_run is lifted.",
    }


def _default_rpc_post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "Raydium-LP1/0.4",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=RPC_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc


@dataclass(frozen=True)
class BalanceResult:
    address: str
    lamports: int
    sol: float
    rpc_url: str
    ok: bool
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "lamports": self.lamports,
            "sol": self.sol,
            "rpc_url": self.rpc_url,
            "ok": self.ok,
            "error": self.error,
        }


def fetch_sol_balance(
    address: str,
    rpc_urls: Iterable[str],
    *,
    rpc_post: RpcCaller | None = None,
) -> BalanceResult:
    """Call ``getBalance`` against the first reachable RPC URL.

    On failure across all URLs we return an ``ok=False`` result instead of
    raising, so the scanner can keep running without a wallet balance.
    """

    caller = rpc_post or _default_rpc_post
    last_error = "no rpc urls configured"
    for url in rpc_urls:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
        try:
            response = caller(url, payload)
        except RuntimeError as exc:
            last_error = str(exc)
            continue
        if not isinstance(response, dict):
            last_error = "rpc returned non-object"
            continue
        if "error" in response and response["error"]:
            last_error = f"rpc error: {response['error']}"
            continue
        result = response.get("result")
        lamports: int | None = None
        if isinstance(result, dict):
            value = result.get("value")
            if isinstance(value, (int, float)):
                lamports = int(value)
        elif isinstance(result, (int, float)):
            lamports = int(result)
        if lamports is None:
            last_error = "rpc returned no lamport value"
            continue
        return BalanceResult(
            address=address,
            lamports=lamports,
            sol=lamports / LAMPORTS_PER_SOL,
            rpc_url=url,
            ok=True,
        )
    return BalanceResult(
        address=address,
        lamports=0,
        sol=0.0,
        rpc_url="",
        ok=False,
        error=last_error,
    )


@dataclass(frozen=True)
class PositionCapacity:
    sol_balance: float
    position_size_sol: float
    max_positions: int
    reserved_sol: float
    available_sol: float

    def to_dict(self) -> dict:
        return {
            "sol_balance": self.sol_balance,
            "position_size_sol": self.position_size_sol,
            "max_positions": self.max_positions,
            "reserved_sol": self.reserved_sol,
            "available_sol": self.available_sol,
        }


def compute_capacity(
    sol_balance: float,
    *,
    position_size_sol: float = DEFAULT_POSITION_SIZE_SOL,
    reserve_sol: float = 0.02,
) -> PositionCapacity:
    """Compute ``floor(available / position_size)`` capacity.

    ``reserve_sol`` is held back for network fees etc.
    """

    if position_size_sol <= 0:
        raise WalletError("position_size_sol must be > 0")
    reserve = max(0.0, float(reserve_sol))
    available = max(0.0, float(sol_balance) - reserve)
    # Small epsilon to keep floating-point arithmetic (e.g. 0.32 - 0.02) from
    # silently swallowing a whole position when the user thinks they have
    # exactly N units.
    raw = available / position_size_sol if position_size_sol > 0 else 0.0
    max_positions = int(math.floor(raw + 1e-9)) if available > 0 else 0
    return PositionCapacity(
        sol_balance=float(sol_balance),
        position_size_sol=float(position_size_sol),
        max_positions=max_positions,
        reserved_sol=reserve,
        available_sol=available,
    )
