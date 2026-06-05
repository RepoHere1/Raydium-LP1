"""Harvest accrued CLMM fees to pay-type (not junker / non-pay leg).

Raydium UI harvest uses ``decreaseLiquidity`` with zero liquidity removal, paying
fees into both pool token ATAs. This module does the same on-chain step, then
optionally Jupiter-swaps only the *non-pay* fee leg into the resolved pay mint.
"""

from __future__ import annotations

from typing import Any, Mapping

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def harvest_options_for_pool(
    pool: Mapping[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    """Node payload: pay output mint, keep set, SOL balance flag."""

    from raydium_lp1.lp_junk_to_pay import close_position_pay_trash_options, keep_mints_for_pool
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.routes import WSOL_MINT

    pay = resolve_pay_mint(pool, config)
    trash = close_position_pay_trash_options(pool, config)
    pay_mint = str(trash.get("trash_output_mint") or "")
    return {
        "pay_symbol": pay.pay_symbol if pay else None,
        "non_pay_symbol": pay.alt_symbol if pay else None,
        "trash_output_mint": pay_mint,
        "trash_keep_mints": trash.get("trash_keep_mints") or sorted(keep_mints_for_pool(pool, config)),
        "use_sol_balance": pay_mint == WSOL_MINT,
        "sweep_non_pay_to_pay_type": True,
    }


def harvest_clmm_position_fees(
    position_nft_mint: str,
    *,
    pool: Mapping[str, Any] | None = None,
    config: Any | None = None,
    slippage_bps: int = 100,
    priority_fee_micro_lamports: int | None = None,
    fee_guard_settings: dict[str, Any] | None = None,
    sweep_non_pay_to_pay_type: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Harvest fees for one open position; keep liquidity in range."""

    from raydium_lp1 import raydium_clmm
    from raydium_lp1.fee_guard import cap_priority_micro, fee_config_from_settings
    from raydium_lp1.lp_selection import fetch_pool_by_id

    if pool is None:
        chain = raydium_clmm._run_script("list_owner_positions.mjs", {}, timeout=60.0)
        pid = None
        for row in chain.get("positions") or []:
            if str(row.get("position_nft_mint")) == str(position_nft_mint).strip():
                pid = str(row.get("pool_id") or "")
                break
        if not pid:
            return {"ok": False, "error": "position not found on chain"}
        from raydium_lp1.scanner import ScannerConfig

        pool = fetch_pool_by_id(pid, config=config or ScannerConfig.from_file(REPO / "config" / "settings.json"))

    opts = harvest_options_for_pool(pool, config)
    cfg = fee_config_from_settings(fee_guard_settings)
    pri = cap_priority_micro(priority_fee_micro_lamports, cfg)

    result = raydium_clmm.harvest_clmm_fees(
        position_nft_mint=str(position_nft_mint).strip(),
        slippage_bps=int(slippage_bps),
        trash_output_mint=opts["trash_output_mint"],
        trash_keep_mints=opts["trash_keep_mints"],
        sweep_non_pay_to_pay_type=bool(sweep_non_pay_to_pay_type),
        use_sol_balance=bool(opts.get("use_sol_balance")),
        priority_fee_micro_lamports=pri,
        fee_guard_settings=fee_guard_settings,
        timeout=timeout,
    )
    result["pay_type_symbol"] = opts.get("pay_symbol")
    result["non_pay_symbol"] = opts.get("non_pay_symbol")
    return result


def harvest_all_open_position_fees(
    *,
    config: Any | None = None,
    pool_id: str | None = None,
    fee_guard_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Harvest every position with liquidity > 0 (optional filter by pool_id)."""

    from raydium_lp1 import raydium_clmm
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.scanner import ScannerConfig

    sc = config or ScannerConfig.from_file(REPO / "config" / "settings.json")
    chain = raydium_clmm._run_script("list_owner_positions.mjs", {}, timeout=120.0)
    if not chain.get("ok"):
        return {"ok": False, "error": chain.get("error") or "list positions failed"}

    pool_cache: dict[str, Mapping[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for pos in chain.get("positions") or []:
        if int(pos.get("liquidity") or 0) <= 0:
            continue
        pid = str(pos.get("pool_id") or "")
        if pool_id and pid != pool_id.strip():
            continue
        nft = str(pos.get("position_nft_mint") or "")
        if not nft:
            continue
        if pid not in pool_cache:
            try:
                pool_cache[pid] = fetch_pool_by_id(pid, config=sc)
            except Exception as exc:
                pool_cache[pid] = {"id": pid, "error": str(exc)}
        pool_row = pool_cache[pid]
        if pool_row.get("error"):
            rows.append({"nft": nft, "pool_id": pid, "ok": False, "error": pool_row["error"]})
            continue
        hr = harvest_clmm_position_fees(
            nft,
            pool=pool_row,
            config=sc,
            fee_guard_settings=fee_guard_settings,
        )
        rows.append({"nft": nft, "pool_id": pid, **hr})

    ok_count = sum(1 for r in rows if r.get("ok"))
    return {
        "ok": ok_count > 0 and ok_count == len(rows),
        "harvested": ok_count,
        "total": len(rows),
        "results": rows,
    }
