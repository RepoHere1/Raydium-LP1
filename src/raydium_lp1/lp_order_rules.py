"""Universal LP open/close order rules (ONE PAY funding, trash→SOL sweep, abandoned pools).

Buy / open rules (enforced before any live CLMM open):
- Run ``lp_rent_escrow.estimate_open_rent_escrow`` via ``fee_guard.assert_clmm_open_allowed``.
- **Never** exceed ``max_rent_escrow_pct_of_deposit`` (default 10%) on estimated *sunk*
  (non-recoverable) tick-array rent vs deposit USD — adjustable in dashboard settings.
- Literal pool min/max full range is always blocked regardless of cap.
"""

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
    ensure_burn_nft: bool = True,
    priority_fee_micro_lamports: int | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Close CLMM position; burn empty NFT; sweep non-stable trash legs to SOL."""

    from raydium_lp1 import raydium_clmm

    result = raydium_clmm.close_position(
        position_nft_mint=position_nft_mint,
        slippage_bps=slippage_bps,
        keep_position=keep_position,
        ensure_burn_nft=ensure_burn_nft,
        payout_as="SOL",
        sweep_trash_to_sol=close_sweep_trash_enabled(config),
        trash_swap_max_attempts=close_trash_swap_attempts(config),
        priority_fee_micro_lamports=priority_fee_micro_lamports,
        timeout=timeout,
    )
    if result.get("ok"):
        from raydium_lp1.lp_wallet_settlement import settle_wallet_after_trade

        result["wallet_settlement"] = settle_wallet_after_trade(sweep_junk=True)
    return result


def burn_empty_clmm_nft(
    position_nft_mint: str,
    *,
    priority_fee_micro_lamports: int | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Burn a zero-liquidity position NFT (Raydium ghost row cleanup)."""

    from raydium_lp1 import raydium_clmm

    return raydium_clmm.burn_position_nft(
        position_nft_mint=position_nft_mint,
        priority_fee_micro_lamports=priority_fee_micro_lamports,
        timeout=timeout,
    )


def burn_all_empty_clmm_nfts(
    *,
    positions: list[dict[str, Any]] | None = None,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Burn every wallet position with liquidity 0 (optional pre-fetched list)."""

    from raydium_lp1.raydium_clmm import _run_script

    rows = positions
    if rows is None:
        chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
        if not chain.get("ok"):
            return [{"ok": False, "error": chain.get("error") or "list_owner_positions failed"}]
        rows = chain.get("positions") or []

    results: list[dict[str, Any]] = []
    for pos in rows:
        nft = str(pos.get("position_nft_mint") or "").strip()
        liq = int(pos.get("liquidity") or 0)
        if not nft or liq != 0:
            continue
        try:
            br = burn_empty_clmm_nft(nft, timeout=timeout)
        except Exception as exc:
            br = {"ok": False, "error": str(exc)}
        results.append({
            "nft": nft,
            "pool_id": pos.get("pool_id"),
            "burn": br,
        })
    return results
