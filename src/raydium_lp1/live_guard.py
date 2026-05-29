"""On-chain spend guard — all trade/LP entry points call this before signing."""

from __future__ import annotations

from raydium_lp1.mode_toggle import ModeBlockedError, require_live

__all__ = ["ModeBlockedError", "guard_onchain", "require_live"]


def guard_onchain(operation: str) -> None:
    """Raise :class:`ModeBlockedError` unless ``config/settings.json`` mode is ``live``."""

    require_live(operation)
