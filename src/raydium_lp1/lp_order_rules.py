"""Universal LP open/close order rules (ONE PAY funding, trash→SOL sweep, abandoned pools)."""

from __future__ import annotations

from typing import Any

# TSLAX/USDC — failed Token-2022 open; do not retry.
ABANDONED_POOL_IDS = frozenset({
    "HHQUnUbmWLrYzkscDY1C3deEFbGtiGBGoHjpANogmvum",
})

DEFAULT_CLOSE_SWEEP_TRASH = True
DEFAULT_CLOSE_TRASH_SWAP_ATTEMPTS = 2


def pool_open_blocked(pool_id: str, config: Any | None = None) -> str | None:
    pid = str(pool_id or "").strip()
    if pid in ABANDONED_POOL_IDS:
        return (
            f"Pool {pid} is abandoned (TSLAX/USDC open killed). "
            "Remove from blocked list in lp_order_rules.py to retry."
        )
    extra = set(getattr(config, "blocked_pool_ids", None) or ())
    if pid and pid in extra:
        return f"Pool {pid} is in settings blocked_pool_ids."
    return None


def close_sweep_trash_enabled(config: Any | None = None) -> bool:
    if config is None:
        return DEFAULT_CLOSE_SWEEP_TRASH
    return bool(getattr(config, "lp_close_sweep_trash_to_sol", DEFAULT_CLOSE_SWEEP_TRASH))


def close_trash_swap_attempts(config: Any | None = None) -> int:
    if config is None:
        return DEFAULT_CLOSE_TRASH_SWAP_ATTEMPTS
    return max(1, int(getattr(config, "lp_close_trash_swap_attempts", DEFAULT_CLOSE_TRASH_SWAP_ATTEMPTS)))


def close_clmm_position(
    position_nft_mint: str,
    *,
    config: Any | None = None,
    slippage_bps: int = 100,
    keep_position: bool = False,
    priority_fee_micro_lamports: int | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Close CLMM position; always sweep non-stable trash legs to SOL (2 tries, then abandon)."""

    from raydium_lp1 import raydium_clmm

    return raydium_clmm.close_position(
        position_nft_mint=position_nft_mint,
        slippage_bps=slippage_bps,
        keep_position=keep_position,
        payout_as="SOL",
        sweep_trash_to_sol=close_sweep_trash_enabled(config),
        trash_swap_max_attempts=close_trash_swap_attempts(config),
        priority_fee_micro_lamports=priority_fee_micro_lamports,
        timeout=timeout,
    )
