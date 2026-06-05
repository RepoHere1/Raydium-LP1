"""Per-position open economics: sunk rent, fees, break-even fee income."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[2]
OPEN_ATTEMPTS_PATH = REPO / "reports" / "open_attempts_by_pool.json"

OPEN_ECONOMICS_TIPS: tuple[str, ...] = (
    "Raydium locks ~0.008 SOL position rent (recoverable on close) — not 0.055+ burned per open.",
    "Active pools rarely charge new tick-array rent; LP1 no longer assumes 0.072 SOL sunk every time.",
    "Pre-fund USDC/USDT in-wallet to skip a Jupiter funding swap (extra tx fee).",
    "Keep ~0.02–0.03 SOL for USDC-pay opens; failed txs still cost network fees only.",
    "Enable lp_rent_conservative_estimates only if you want the old pessimistic rent model.",
)


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _deposit_usd_from_row(row: Mapping[str, Any], sol_price: float = 180.0) -> float:
    sl = row.get("spend_less_get_more")
    if isinstance(sl, dict) and sl.get("effective_deposit_usd") is not None:
        return _f(sl["effective_deposit_usd"])
    pay = str(row.get("input_pay_symbol") or row.get("lp_pay_symbol") or "").upper()
    human = _f(row.get("input_amount_human"))
    if pay in ("USDC", "USDT", "USD1"):
        return human
    if human > 0:
        px = sol_price if sol_price > 0 else 180.0
        return human * px
    return _f(row.get("value_usd"))


def _rent_parts(
    row: Mapping[str, Any],
    *,
    sol_price: float,
) -> tuple[float, float, float]:
    """Return (sunk_usd, recoverable_usd, network_fee_usd)."""

    rent: dict[str, Any] = {}
    analysis = row.get("spend_less_cost_analysis")
    if isinstance(analysis, dict):
        re = analysis.get("rent_escrow_estimate")
        if isinstance(re, dict):
            rent = re
    if not rent:
        sl = row.get("spend_less_get_more")
        if isinstance(sl, dict):
            re = sl.get("rent_escrow")
            if isinstance(re, dict):
                rent = re
    if not rent:
        clmm = row.get("clmm_result") if isinstance(row.get("clmm_result"), dict) else {}
        fg = clmm.get("fee_guard_estimate") or row.get("fee_guard_estimate") or {}
        if isinstance(fg, dict):
            re = fg.get("rent_escrow")
            if isinstance(re, dict):
                rent = re

    px = _f(rent.get("sol_price_usd"), sol_price) if rent else sol_price
    sunk_usd = _f(rent.get("sunk_usd")) if rent else 0.0
    if sunk_usd <= 0 and rent:
        sunk_usd = _f(rent.get("sunk_sol_est")) * px
    rec_usd = _f(rent.get("recoverable_sol_est")) * px if rent else 0.0
    if rec_usd <= 0 and rent:
        rec_usd = _f(rent.get("rent_escrow_usd")) - sunk_usd
        rec_usd = max(0.0, rec_usd)

    network_sol = 0.0
    if isinstance(analysis, dict):
        network_sol = _f(analysis.get("total_network_fee_sol"))
        for tx in analysis.get("transactions") or []:
            if isinstance(tx, dict) and tx.get("status") == "failed":
                network_sol += _f(tx.get("fee_sol"))
    if network_sol <= 0:
        clmm = row.get("clmm_result") if isinstance(row.get("clmm_result"), dict) else {}
        fg = clmm.get("fee_guard_estimate") or {}
        if isinstance(fg, dict):
            network_sol = _f(fg.get("estimated_total_sol")) or _f(fg.get("base_fee_sol"))

    return sunk_usd, max(0.0, rec_usd), network_sol * px


def _funding_swap_usd(row: Mapping[str, Any], sol_price: float) -> float:
    analysis = row.get("spend_less_cost_analysis")
    if isinstance(analysis, dict) and len(analysis.get("transactions") or []) > 1:
        txs = analysis.get("transactions") or []
        fee_sol = sum(_f(t.get("fee_sol")) for t in txs[1:] if isinstance(t, dict))
        return fee_sol * sol_price
    pf = row.get("pay_funding")
    if isinstance(pf, dict) and pf.get("funded"):
        plan = pf.get("funding_plan") or {}
        return _f(plan.get("estimated_sol_swap")) * sol_price
    return 0.0


def _est_fee_share_24h_usd(row: Mapping[str, Any], deposit_usd: float) -> float | None:
    if row.get("fees_collected_usd") is not None:
        return _f(row.get("fees_collected_usd"))
    tvl = _f(row.get("liquidity_usd"))
    fee_pool = _f(row.get("fee_24h_usd"))
    if fee_pool <= 0 or tvl <= 0 or deposit_usd <= 0:
        return None
    return fee_pool * (deposit_usd / tvl)


def build_open_cost_summary(
    row: Mapping[str, Any],
    *,
    sol_price_usd: float = 180.0,
    failed_attempts_usd: float = 0.0,
) -> dict[str, Any]:
    """Summarize open costs and break-even fee income for one position row."""

    deposit_usd = _deposit_usd_from_row(row, sol_price_usd)
    sunk_usd, recoverable_usd, network_usd = _rent_parts(row, sol_price=sol_price_usd)
    swap_usd = _funding_swap_usd(row, sol_price_usd)
    failed_usd = max(0.0, float(failed_attempts_usd))

    non_recoverable_usd = round(sunk_usd + network_usd + swap_usd + failed_usd, 4)
    total_cash_out_usd = round(deposit_usd + non_recoverable_usd, 4)
    break_even_fee_usd = non_recoverable_usd
    break_even_pct = (
        round(100.0 * break_even_fee_usd / deposit_usd, 2) if deposit_usd > 0 else None
    )

    est_fee_24h = _est_fee_share_24h_usd(row, deposit_usd)
    days_to_breakeven = None
    if est_fee_24h and est_fee_24h > 0 and break_even_fee_usd > 0:
        days_to_breakeven = round(break_even_fee_usd / est_fee_24h, 2)

    sunk_pct_dep = round(100.0 * sunk_usd / deposit_usd, 1) if deposit_usd > 0 else None

    return {
        "deposit_usd": round(deposit_usd, 4),
        "sunk_rent_usd": round(sunk_usd, 4),
        "recoverable_rent_usd": round(recoverable_usd, 4),
        "network_fees_usd": round(network_usd, 4),
        "funding_swap_usd": round(swap_usd, 4),
        "failed_attempts_usd": round(failed_usd, 4),
        "non_recoverable_usd": non_recoverable_usd,
        "total_cash_out_usd": total_cash_out_usd,
        "break_even_fee_income_usd": break_even_fee_usd,
        "break_even_pct_of_deposit": break_even_pct,
        "est_fee_share_24h_usd": round(est_fee_24h, 4) if est_fee_24h is not None else None,
        "days_to_breakeven_at_current_fee_rate": days_to_breakeven,
        "sunk_pct_of_deposit": sunk_pct_dep,
        "tips": list(OPEN_ECONOMICS_TIPS[:3]),
    }


def enrich_position_row(row: dict[str, Any], *, sol_price_usd: float = 180.0) -> dict[str, Any]:
    """Attach fresh ``open_economics`` to a position dict (mutates and returns)."""

    out = dict(row)
    pid = str(out.get("pool_id") or "")
    out["open_economics"] = build_open_cost_summary(
        out,
        sol_price_usd=sol_price_usd,
        failed_attempts_usd=failed_attempts_usd_for_pool(pid),
    )
    return out


def enrich_positions(
    rows: list[dict[str, Any]],
    *,
    sol_price_usd: float = 180.0,
) -> list[dict[str, Any]]:
    return [enrich_position_row(r, sol_price_usd=sol_price_usd) for r in rows if isinstance(r, dict)]


def _load_attempt_ledger() -> dict[str, Any]:
    if not OPEN_ATTEMPTS_PATH.is_file():
        return {"pools": {}, "updated_at": None}
    try:
        raw = json.loads(OPEN_ATTEMPTS_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"pools": {}, "updated_at": None}
    except (OSError, json.JSONDecodeError):
        return {"pools": {}, "updated_at": None}


def _save_attempt_ledger(data: dict[str, Any]) -> None:
    OPEN_ATTEMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(UTC).isoformat()
    OPEN_ATTEMPTS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def record_failed_open_attempt(
    pool_id: str,
    *,
    cost_usd: float = 0.0,
    error: str | None = None,
    signature: str | None = None,
) -> None:
    """Track failed LIVE open tries per pool (network fees, no position)."""

    pid = str(pool_id or "").strip()
    if not pid:
        return
    led = _load_attempt_ledger()
    pools = dict(led.get("pools") or {})
    entry = dict(pools.get(pid) or {"attempts": [], "total_failed_cost_usd": 0.0})
    attempts = list(entry.get("attempts") or [])
    attempts.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "cost_usd": round(float(cost_usd), 4),
            "error": (error or "")[:200],
            "signature": signature or "",
        }
    )
    entry["attempts"] = attempts[-20:]
    entry["total_failed_cost_usd"] = round(
        sum(float(a.get("cost_usd") or 0) for a in entry["attempts"]),
        4,
    )
    pools[pid] = entry
    led["pools"] = pools
    _save_attempt_ledger(led)


def failed_attempts_usd_for_pool(pool_id: str) -> float:
    pid = str(pool_id or "").strip()
    if not pid:
        return 0.0
    pools = (_load_attempt_ledger().get("pools") or {})
    entry = pools.get(pid) or {}
    return float(entry.get("total_failed_cost_usd") or 0.0)


def record_failed_open_from_result(pool_id: str, result: Mapping[str, Any], *, sol_price: float = 180.0) -> None:
    """Parse an open_clmm_candidate failure and append to per-pool attempt ledger."""

    cost_usd = 0.0
    sig = ""
    clmm = result.get("clmm") if isinstance(result.get("clmm"), dict) else {}
    sig = str(clmm.get("signature") or result.get("tx") or "")
    if sig:
        try:
            from raydium_lp1.lp_tx_cost_analysis import analyze_transaction
            from raydium_lp1.raydium_clmm import wallet_balance

            wb = wallet_balance()
            tx = analyze_transaction(sig, wallet=str(wb.get("address") or ""), rpc_url=str(wb.get("rpc_url") or ""))
            if tx.fee_sol > 0:
                cost_usd = tx.fee_sol * sol_price
        except Exception:
            pass
    record_failed_open_attempt(
        pool_id,
        cost_usd=cost_usd,
        error=str(result.get("error") or ""),
        signature=sig or None,
    )
