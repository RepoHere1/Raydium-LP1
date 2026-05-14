"""HoneypotGuard: refuse pools whose base token has on-chain trading frictions.

The name to remember is **honeypot_guard**. The exact filter that vetoes a
buy is **HoneypotGuard.sell_tax_cap** and **HoneypotGuard.authority_traps**.

What it looks at, in plain English:

1. **Sell tax / transfer fee.** The SPL Token-2022 program supports an on-chain
   "TransferFeeConfig" extension. When set, every transfer of that token has
   a percentage skimmed off automatically. That is *the* on-chain version of
   a "sell tax". This guard reads the current `transfer_fee_basis_points`
   from the mint and rejects the pool if the implied sell-tax percent exceeds
   `max_sell_tax_percent`.

2. **Freeze authority.** A mint with `freeze_authority` set means somebody
   off-chain can freeze your token account (`SetAuthority` -> `FreezeAccount`).
   That is a one-click hard rug. The classic trustworthy stables (USDC,
   USDT) do have freeze authority on purpose; you should *whitelist* their
   mints in `honeypot_guard.allowed_freeze_authority_mints` if you trust them.

3. **Transfer hook.** Token-2022's TransferHook extension lets the issuer
   point at a program that runs on every transfer. That program can revert
   any sell. It is a sell-blocker by design and we reject by default.

4. **Permanent delegate.** Token-2022's PermanentDelegate extension lets the
   delegate move tokens out of *any* account. Effectively, "we can take your
   tokens back whenever we want." Rejected by default.

This module talks to a Solana JSON-RPC URL from `solana_rpc_urls`. If you
have no RPC configured, set `honeypot_guard.fail_open_when_no_rpc` to
`true` to accept pools the guard could not check (default: false = safer).

Settings live under `honeypot_guard` in `config/settings.json`. See SETTINGS.md.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

EXT_TRANSFER_FEE_CONFIG = 1
EXT_PERMANENT_DELEGATE = 12
EXT_TRANSFER_HOOK = 14
EXT_CONFIDENTIAL_TRANSFER_FEE = 16

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

DEFAULT_TRUSTED_FREEZE_MINTS: tuple[str, ...] = (USDC_MINT, USDT_MINT)


@dataclass(frozen=True)
class HoneypotGuardConfig:
    enabled: bool = True
    max_sell_tax_percent: float = 30.0
    reject_if_freeze_authority_set: bool = True
    reject_if_transfer_hook_set: bool = True
    reject_if_permanent_delegate_set: bool = True
    allowed_freeze_authority_mints: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_TRUSTED_FREEZE_MINTS)
    )
    fail_open_when_no_rpc: bool = False
    rpc_timeout_seconds: float = 8.0

    @classmethod
    def from_raw(cls, raw: Any) -> "HoneypotGuardConfig":
        if not isinstance(raw, dict):
            return cls()
        whitelist_raw = raw.get("allowed_freeze_authority_mints", DEFAULT_TRUSTED_FREEZE_MINTS)
        whitelist = frozenset(str(m).strip() for m in whitelist_raw if str(m).strip())
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            max_sell_tax_percent=float(raw.get("max_sell_tax_percent", cls.max_sell_tax_percent)),
            reject_if_freeze_authority_set=bool(
                raw.get("reject_if_freeze_authority_set", cls.reject_if_freeze_authority_set)
            ),
            reject_if_transfer_hook_set=bool(
                raw.get("reject_if_transfer_hook_set", cls.reject_if_transfer_hook_set)
            ),
            reject_if_permanent_delegate_set=bool(
                raw.get("reject_if_permanent_delegate_set", cls.reject_if_permanent_delegate_set)
            ),
            allowed_freeze_authority_mints=whitelist,
            fail_open_when_no_rpc=bool(raw.get("fail_open_when_no_rpc", cls.fail_open_when_no_rpc)),
            rpc_timeout_seconds=float(raw.get("rpc_timeout_seconds", cls.rpc_timeout_seconds)),
        )


@dataclass(frozen=True)
class MintInspection:
    """What we managed to learn about a token mint by reading its account data."""

    mint_address: str
    owner_program: str
    freeze_authority_set: bool
    mint_authority_set: bool
    transfer_fee_basis_points: int | None
    has_transfer_hook: bool
    has_permanent_delegate: bool
    decimals: int
    raw_data_length: int

    @property
    def is_token_2022(self) -> bool:
        return self.owner_program == TOKEN_2022_PROGRAM_ID

    @property
    def sell_tax_percent(self) -> float:
        if self.transfer_fee_basis_points is None:
            return 0.0
        return self.transfer_fee_basis_points / 100.0


def parse_mint_data(data: bytes) -> dict[str, Any]:
    """Decode an SPL/Token-2022 mint account. Robust to truncated data."""

    info: dict[str, Any] = {
        "mint_authority_set": False,
        "freeze_authority_set": False,
        "decimals": 0,
        "transfer_fee_basis_points": None,
        "has_transfer_hook": False,
        "has_permanent_delegate": False,
        "extensions_seen": [],
    }
    if len(data) < 82:
        return info

    mint_option = int.from_bytes(data[0:4], "little", signed=False)
    info["mint_authority_set"] = mint_option == 1
    info["decimals"] = data[44]
    freeze_option = int.from_bytes(data[46:50], "little", signed=False)
    info["freeze_authority_set"] = freeze_option == 1

    if len(data) <= 165:
        return info

    offset = 166
    while offset + 4 <= len(data):
        ext_type = int.from_bytes(data[offset : offset + 2], "little", signed=False)
        ext_len = int.from_bytes(data[offset + 2 : offset + 4], "little", signed=False)
        ext_data_start = offset + 4
        ext_data_end = ext_data_start + ext_len
        if ext_data_end > len(data) or ext_type == 0:
            break
        info["extensions_seen"].append(ext_type)
        if ext_type == EXT_TRANSFER_FEE_CONFIG and ext_len >= 108:
            # TransferFeeConfig layout:
            #  0..32  transfer_fee_config_authority   (OptionalNonZeroPubkey)
            # 32..64  withdraw_withheld_authority     (OptionalNonZeroPubkey)
            # 64..72  withheld_amount                  (u64)
            # 72..90  older_transfer_fee  {epoch u64, max u64, bp u16}
            # 90..108 newer_transfer_fee  {epoch u64, max u64, bp u16}
            # We read the *newer* basis points (the fee that applies now or next epoch).
            bp_start = ext_data_start + 90 + 16
            info["transfer_fee_basis_points"] = int.from_bytes(
                data[bp_start : bp_start + 2], "little", signed=False
            )
        elif ext_type == EXT_TRANSFER_HOOK:
            info["has_transfer_hook"] = True
        elif ext_type == EXT_PERMANENT_DELEGATE:
            info["has_permanent_delegate"] = True
        offset = ext_data_end

    return info


def _post_rpc(rpc_url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        rpc_url,
        data=data,
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "Raydium-LP1/0.3 HoneypotGuard",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured RPC read
        return json.loads(response.read().decode("utf-8"))


def fetch_mint_inspection(rpc_url: str, mint_address: str, timeout: float = 8.0) -> MintInspection | None:
    """Return a MintInspection for `mint_address`, or None if the RPC didn't help."""

    if not mint_address:
        return None
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [mint_address, {"encoding": "base64"}],
    }
    try:
        response = _post_rpc(rpc_url, payload, timeout=timeout)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    result = (response or {}).get("result") or {}
    value = result.get("value") or {}
    data_field = value.get("data")
    owner = value.get("owner") or ""
    if not isinstance(data_field, list) or len(data_field) < 1:
        return None
    try:
        raw_bytes = base64.b64decode(data_field[0])
    except (TypeError, ValueError):
        return None
    parsed = parse_mint_data(raw_bytes)
    return MintInspection(
        mint_address=mint_address,
        owner_program=owner,
        freeze_authority_set=bool(parsed["freeze_authority_set"]),
        mint_authority_set=bool(parsed["mint_authority_set"]),
        transfer_fee_basis_points=parsed["transfer_fee_basis_points"],
        has_transfer_hook=bool(parsed["has_transfer_hook"]),
        has_permanent_delegate=bool(parsed["has_permanent_delegate"]),
        decimals=int(parsed["decimals"]),
        raw_data_length=len(raw_bytes),
    )


def evaluate_inspection(
    inspection: MintInspection,
    config: HoneypotGuardConfig,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails) given a fetched MintInspection."""

    if inspection.transfer_fee_basis_points is not None:
        tax_pct = inspection.sell_tax_percent
        if tax_pct > config.max_sell_tax_percent:
            return False, (
                f"on-chain sell tax {tax_pct:.2f}% exceeds max {config.max_sell_tax_percent:.2f}% "
                f"(transfer_fee_basis_points={inspection.transfer_fee_basis_points})"
            )

    if (
        config.reject_if_freeze_authority_set
        and inspection.freeze_authority_set
        and inspection.mint_address not in config.allowed_freeze_authority_mints
    ):
        return False, "freeze authority is set on the base token (owner can freeze your wallet)"

    if config.reject_if_transfer_hook_set and inspection.has_transfer_hook:
        return False, "Token-2022 TransferHook is set; issuer can block any sale"

    if config.reject_if_permanent_delegate_set and inspection.has_permanent_delegate:
        return False, "Token-2022 PermanentDelegate is set; owner can claw back tokens"

    return True, None


def evaluate_honeypot_guard(
    base_mint: str,
    config: HoneypotGuardConfig,
    rpc_urls: list[str],
    cache: dict[str, MintInspection | None] | None = None,
) -> tuple[bool, str | None, MintInspection | None]:
    """Top-level guard: fetch + evaluate for one base mint.

    `cache` lets the scanner reuse one RPC call across many pools that share
    the same base token. The cache stores both successful and failed lookups
    (the latter as None) so we don't hammer a flaky RPC.
    """

    if not config.enabled:
        return True, None, None
    if not base_mint:
        return True, None, None

    if cache is not None and base_mint in cache:
        inspection = cache[base_mint]
    else:
        inspection = None
        for rpc_url in rpc_urls:
            inspection = fetch_mint_inspection(rpc_url, base_mint, timeout=config.rpc_timeout_seconds)
            if inspection is not None:
                break
        if cache is not None:
            cache[base_mint] = inspection

    if inspection is None:
        if not rpc_urls:
            if config.fail_open_when_no_rpc:
                return True, None, None
            return False, "no Solana RPC configured; honeypot_guard cannot verify base token", None
        if config.fail_open_when_no_rpc:
            return True, None, None
        return False, "all configured RPCs failed; honeypot_guard could not verify base token", None

    ok, reason = evaluate_inspection(inspection, config)
    return ok, reason, inspection
