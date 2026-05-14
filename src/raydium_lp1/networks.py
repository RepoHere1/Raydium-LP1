"""Multi-network adapter scaffolding for Raydium-LP1.

Today only Solana is wired end-to-end. Ethereum and Base are stubbed with
the same interface so they can later plug in without changes to the rest
of the scanner.

Each network is represented by a :class:`NetworkAdapter` that exposes:

* ``key`` / ``display_name`` / ``native_symbol`` -- metadata
* ``rpc_post(url, payload)`` -- raw JSON-RPC POST
* ``fetch_native_balance(address, rpc_urls)`` -- returns a wallet.BalanceResult-shaped dict
* ``swap_quote_url(input_mint, output_mint, amount, slippage_bps)`` -- where to look up routes

Choosing a network is a simple setting (``"network": "solana"`` etc.); the
scanner asks :func:`get_adapter` for the right implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable
from urllib.parse import urlencode

from raydium_lp1 import wallet


NETWORK_SOLANA = "solana"
NETWORK_ETHEREUM = "ethereum"
NETWORK_BASE = "base"
SUPPORTED_NETWORKS = (NETWORK_SOLANA, NETWORK_ETHEREUM, NETWORK_BASE)


class NetworkNotSupportedError(NotImplementedError):
    """Raised by stub adapters when a method is called that isn't wired yet."""


@dataclass
class NetworkAdapter:
    """Base adapter. Concrete networks subclass and override."""

    key: str
    display_name: str
    native_symbol: str
    quote_api_base: str = ""
    supports_live: bool = False
    notes: str = ""

    def fetch_native_balance(self, address: str, rpc_urls: Iterable[str]) -> dict:
        raise NetworkNotSupportedError(
            f"{self.display_name} balance lookup is not implemented yet"
        )

    def swap_quote_url(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int
    ) -> str:
        raise NetworkNotSupportedError(
            f"{self.display_name} swap quoting is not implemented yet"
        )

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "native_symbol": self.native_symbol,
            "supports_live": self.supports_live,
            "notes": self.notes,
        }


@dataclass
class SolanaAdapter(NetworkAdapter):
    key: str = NETWORK_SOLANA
    display_name: str = "Solana"
    native_symbol: str = "SOL"
    quote_api_base: str = "https://quote-api.jup.ag/v6"
    supports_live: bool = True
    rpc_post: Callable[[str, dict], dict] | None = None
    notes: str = "Default network. Uses Jupiter for routing and Solana RPC for balances."

    def fetch_native_balance(self, address: str, rpc_urls: Iterable[str]) -> dict:
        # Look the default poster up at call time so unittest.mock.patch on
        # ``wallet._default_rpc_post`` works for end-to-end tests/demos.
        caller = self.rpc_post or wallet._default_rpc_post
        result = wallet.fetch_sol_balance(address, rpc_urls, rpc_post=caller)
        return result.to_dict()

    def swap_quote_url(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int
    ) -> str:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": slippage_bps,
            "swapMode": "ExactIn",
        }
        return f"{self.quote_api_base}/quote?{urlencode(params)}"


@dataclass
class EthereumAdapter(NetworkAdapter):
    key: str = NETWORK_ETHEREUM
    display_name: str = "Ethereum"
    native_symbol: str = "ETH"
    quote_api_base: str = ""
    supports_live: bool = False
    notes: str = "Stub: extend to plug in 0x / 1inch / Uniswap routers."


@dataclass
class BaseAdapter(NetworkAdapter):
    key: str = NETWORK_BASE
    display_name: str = "Base"
    native_symbol: str = "ETH"
    quote_api_base: str = ""
    supports_live: bool = False
    notes: str = "Stub: extend to plug in Aerodrome / 0x v2 on Base."


_REGISTRY: dict[str, type[NetworkAdapter]] = {
    NETWORK_SOLANA: SolanaAdapter,
    NETWORK_ETHEREUM: EthereumAdapter,
    NETWORK_BASE: BaseAdapter,
}


def normalize_network(name: str | None) -> str:
    key = (name or "").strip().lower() or NETWORK_SOLANA
    if key not in _REGISTRY:
        raise ValueError(f"unsupported network: {name!r}. Supported: {SUPPORTED_NETWORKS}")
    return key


def get_adapter(name: str | None) -> NetworkAdapter:
    key = normalize_network(name)
    return _REGISTRY[key]()


def describe_networks() -> str:
    lines = ["Supported networks:"]
    for key in SUPPORTED_NETWORKS:
        adapter = _REGISTRY[key]()
        status = "LIVE" if adapter.supports_live else "STUB"
        lines.append(
            f"  - {adapter.key:<10} [{status}] {adapter.display_name} "
            f"({adapter.native_symbol}) - {adapter.notes}"
        )
    return "\n".join(lines)
