"""On-chain spend guard — all trade/LP entry points call this before signing."""

from __future__ import annotations

from raydium_lp1.fee_guard import FeeGuardBlockedError, guard_onchain_fee
from raydium_lp1.mode_toggle import ModeBlockedError, require_live

__all__ = ["ModeBlockedError", "FeeGuardBlockedError", "guard_onchain", "require_live"]


def guard_onchain(operation: str, **fee_context: object) -> None:
    """Raise unless mode is live and fee guard allows the spend."""

    require_live(operation)
    guard_onchain_fee(operation, **fee_context)
