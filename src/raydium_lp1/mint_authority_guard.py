"""MintAuthorityGuard: reject base tokens whose mint authority is still live.

The name to remember is **mint_authority_guard**.

What it asks, in plain English:
- A Solana SPL/Token-2022 mint has an optional `mint_authority`. If it is
  still set, somebody can mint unlimited new supply of the token at any
  time. That is the single most common rug pattern: the creator dumps a
  fresh batch into the pool and your LP position becomes worthless.
- The safe state is **mint_authority disabled** (set to `None`). Trustworthy
  tokens like USDC do keep a mint authority because the issuer manages
  supply, so this guard supports a whitelist for those mints.

Implementation notes:
- The mint-authority bit lives in the first 4 bytes of an SPL/Token-2022
  mint account: an `Option<Pubkey>` discriminator whose value is `1` for
  `Some(...)` and `0` for `None`. We piggyback on the same `getAccountInfo`
  RPC call that `honeypot_guard` already makes, so we pay **one** RPC per
  base mint per scan even with both guards enabled.

Behavior on missing/failed RPC matches `honeypot_guard`:
- `fail_open_when_no_rpc=False` (default) -> guard fails closed.
- `fail_open_when_no_rpc=True`           -> guard skips and accepts.

Settings live under `mint_authority_guard` in `config/settings.json`.
See SETTINGS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .honeypot_guard import USDC_MINT, USDT_MINT, MintInspection

DEFAULT_TRUSTED_MINT_AUTHORITY_MINTS: tuple[str, ...] = (USDC_MINT, USDT_MINT)


@dataclass(frozen=True)
class MintAuthorityGuardConfig:
    enabled: bool = True
    reject_if_mint_authority_set: bool = True
    allowed_mint_authority_mints: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_TRUSTED_MINT_AUTHORITY_MINTS)
    )
    fail_open_when_no_rpc: bool = False

    @classmethod
    def from_raw(cls, raw: Any) -> "MintAuthorityGuardConfig":
        if not isinstance(raw, dict):
            return cls()
        whitelist_raw = raw.get(
            "allowed_mint_authority_mints", DEFAULT_TRUSTED_MINT_AUTHORITY_MINTS
        )
        whitelist = frozenset(str(m).strip() for m in whitelist_raw if str(m).strip())
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            reject_if_mint_authority_set=bool(
                raw.get("reject_if_mint_authority_set", cls.reject_if_mint_authority_set)
            ),
            allowed_mint_authority_mints=whitelist,
            fail_open_when_no_rpc=bool(raw.get("fail_open_when_no_rpc", cls.fail_open_when_no_rpc)),
        )


def evaluate_mint_authority_guard(
    inspection: MintInspection | None,
    config: MintAuthorityGuardConfig,
    *,
    has_rpc_configured: bool,
) -> tuple[bool, str | None]:
    """Return (passes, reason_if_fails) using the shared MintInspection."""

    if not config.enabled:
        return True, None

    if inspection is None:
        if not has_rpc_configured:
            if config.fail_open_when_no_rpc:
                return True, None
            return False, (
                "no Solana RPC configured; mint_authority_guard cannot verify base token"
            )
        if config.fail_open_when_no_rpc:
            return True, None
        return False, "all configured RPCs failed; mint_authority_guard could not verify base token"

    if (
        config.reject_if_mint_authority_set
        and inspection.mint_authority_set
        and inspection.mint_address not in config.allowed_mint_authority_mints
    ):
        return False, (
            "mint_authority is still set on the base token "
            "(owner can mint unlimited new supply and dump it into the pool)"
        )

    return True, None


__all__ = [
    "DEFAULT_TRUSTED_MINT_AUTHORITY_MINTS",
    "MintAuthorityGuardConfig",
    "evaluate_mint_authority_guard",
]
