"""Find exit-safe pools printing real USD fees despite low reported APR.

Visual / research signal for dashboard HTML — not wired into LIVE auto-trade yet.
Does not use lp pay-token funding (SOL→USDC/USDT/USD1); that protocol applies to filtered LIVE opens only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Raydium CLMM program id (duplicated here to avoid scanner ↔ cash_anomalies import cycle).
RAYDIUM_CLMM_PROGRAM_ID = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"


@dataclass(frozen=True)
class CashAnomalyConfig:
    enabled: bool = True
    min_fee_24h_usd: float = 25.0
    max_reported_apr: float = 150.0
    top_n: int = 30
    implied_apr_gap_min: float = 10.0


def config_from_scanner(config: Any) -> CashAnomalyConfig:
    return CashAnomalyConfig(
        enabled=bool(getattr(config, "cash_anomaly_enabled", True)),
        min_fee_24h_usd=float(getattr(config, "cash_anomaly_min_fee_usd", 25.0)),
        max_reported_apr=float(getattr(config, "cash_anomaly_max_apr", 150.0)),
        top_n=max(1, int(getattr(config, "cash_anomaly_top_n", 30))),
        implied_apr_gap_min=float(getattr(config, "cash_anomaly_implied_gap_min", 10.0)),
    )


def exit_liquidity_floor_usd(config: Any) -> float:
    hard = float(getattr(config, "hard_exit_min_tvl_usd", 0) or 0)
    soft = float(getattr(config, "min_liquidity_usd", 0) or 0)
    return hard if hard > 0 else soft


def is_clmm_pool(pool: dict[str, Any]) -> bool:
    return str(pool.get("program_id") or "") == RAYDIUM_CLMM_PROGRAM_ID


def pool_exit_eligible(pool: dict[str, Any], floor_usd: float) -> bool:
    if not is_clmm_pool(pool):
        return False
    tvl = float(pool.get("liquidity_usd") or 0)
    if floor_usd > 0 and tvl < floor_usd:
        return False
    return tvl > 0


def implied_apr_from_fees(fee_24h_usd: float, tvl_usd: float) -> float:
    if tvl_usd <= 0:
        return 0.0
    return fee_24h_usd * 365.0 / tvl_usd * 100.0


def _pair_label(pool: dict[str, Any]) -> str:
    a = str(pool.get("mint_a_symbol") or "")
    b = str(pool.get("mint_b_symbol") or "")
    if a or b:
        return f"{a}/{b}"
    return str(pool.get("pair") or "?")


def _sell_route_ok(pool: dict[str, Any]) -> bool | None:
    sell = pool.get("sellability")
    if not isinstance(sell, dict):
        return None
    return bool(sell.get("ok"))


def anomaly_tags(pool: dict[str, Any], cfg: CashAnomalyConfig, scanner_min_apr: float) -> list[str]:
    fee = float(pool.get("fee_24h_usd") or 0)
    apr = float(pool.get("apr") or 0)
    tvl = float(pool.get("liquidity_usd") or 0)
    if fee < cfg.min_fee_24h_usd:
        return []

    implied = implied_apr_from_fees(fee, tvl)
    tags: list[str] = []

    if apr <= cfg.max_reported_apr:
        tags.append("low_apr_high_cash")
    if apr < scanner_min_apr:
        tags.append("below_scanner_min_apr")
    if implied > apr * 1.2 and (implied - apr) >= cfg.implied_apr_gap_min:
        tags.append("apr_understates_cash")
    if fee >= cfg.min_fee_24h_usd * 4 and apr <= cfg.max_reported_apr * 0.5:
        tags.append("heavy_cash_light_apr")

    return tags


def build_cash_anomaly_row(
    pool: dict[str, Any],
    *,
    cfg: CashAnomalyConfig,
    scanner_min_apr: float,
    exit_floor_usd: float,
    candidate_ids: set[str],
) -> dict[str, Any] | None:
    tags = anomaly_tags(pool, cfg, scanner_min_apr)
    if not tags:
        return None

    fee = float(pool.get("fee_24h_usd") or 0)
    apr = float(pool.get("apr") or 0)
    tvl = float(pool.get("liquidity_usd") or 0)
    vol = float(pool.get("volume_24h_usd") or 0)
    implied = implied_apr_from_fees(fee, tvl)
    pid = str(pool.get("id") or pool.get("pool_id") or "")

    return {
        "pool_id": pid,
        "pair": _pair_label(pool),
        "apr": round(apr, 2),
        "tvl_usd": round(tvl, 2),
        "volume_24h_usd": round(vol, 2),
        "cash_24h_usd": round(fee, 2),
        "implied_apr_pct": round(implied, 2),
        "apr_gap_pct": round(implied - apr, 2),
        "exit_floor_usd": round(exit_floor_usd, 2),
        "anomaly_tags": tags,
        "in_candidates": pid in candidate_ids,
        "sell_route_ok": _sell_route_ok(pool),
    }


def build_cash_anomaly_report(
    pools: list[dict[str, Any]],
    config: Any,
    *,
    candidate_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Rank exit-safe CLMM pools where USD fees outrun reported APR."""

    cfg = config_from_scanner(config)
    floor = exit_liquidity_floor_usd(config)
    min_apr = float(getattr(config, "min_apr", 0) or 0)
    ids = candidate_ids or set()

    if not cfg.enabled:
        return {
            "enabled": False,
            "exit_floor_usd": floor,
            "min_fee_24h_usd": cfg.min_fee_24h_usd,
            "max_reported_apr": cfg.max_reported_apr,
            "probed_count": 0,
            "anomaly_count": 0,
            "rows": [],
        }

    rows: list[dict[str, Any]] = []
    probed = 0
    for pool in pools:
        if not pool_exit_eligible(pool, floor):
            continue
        probed += 1
        row = build_cash_anomaly_row(
            pool,
            cfg=cfg,
            scanner_min_apr=min_apr,
            exit_floor_usd=floor,
            candidate_ids=ids,
        )
        if row:
            rows.append(row)

    rows.sort(
        key=lambda r: (
            float(r.get("cash_24h_usd") or 0),
            float(r.get("apr_gap_pct") or 0),
        ),
        reverse=True,
    )
    rows = rows[: cfg.top_n]

    return {
        "enabled": True,
        "exit_floor_usd": floor,
        "min_fee_24h_usd": cfg.min_fee_24h_usd,
        "max_reported_apr": cfg.max_reported_apr,
        "probed_count": probed,
        "anomaly_count": len(rows),
        "rows": rows,
    }


def format_terminal_block(report: dict[str, Any]) -> list[str]:
    """Standard text lines for scanner CLI / dashboard text view."""

    lines: list[str] = []
    if not report.get("enabled"):
        lines.append("ANOMALIES (CASH): disabled in settings")
        return lines

    rows = list(report.get("rows") or [])
    floor = float(report.get("exit_floor_usd") or 0)
    min_fee = float(report.get("min_fee_24h_usd") or 0)
    max_apr = float(report.get("max_reported_apr") or 0)

    lines.append(
        f"ANOMALIES — CASH (exit TVL>={floor:,.0f} USD, fee24>={min_fee:.0f}, "
        f"low-APR ceiling {max_apr:.0f}%): {len(rows)} row(s)"
    )
    if not rows:
        lines.append("  (none this cycle — widen pages or lower cash_anomaly_min_fee_usd)")
        return lines

    lines.append(
        "Columns: PAIR | APR% | TVL USD | CASH 24h USD | implied APR% | gap | POOL_STATE"
    )
    for rank, row in enumerate(rows, start=1):
        tags = ", ".join((row.get("anomaly_tags") or [])[:3])
        cand = " [candidate]" if row.get("in_candidates") else ""
        sell = row.get("sell_route_ok")
        sell_txt = ""
        if sell is True:
            sell_txt = " exit=ok"
        elif sell is False:
            sell_txt = " exit=route?"
        lines.append(
            f"  {rank:>2}. {row.get('pair', '?'):<22} "
            f"APR {float(row.get('apr') or 0):>7.1f}% "
            f"TVL ${float(row.get('tvl_usd') or 0):>10,.0f} "
            f"CASH ${float(row.get('cash_24h_usd') or 0):>8,.2f} "
            f"impl {float(row.get('implied_apr_pct') or 0):>6.1f}% "
            f"gap {float(row.get('apr_gap_pct') or 0):>+6.1f} "
            f"{row.get('pool_id', '')}{cand}{sell_txt}"
        )
        if tags:
            lines.append(f"       tags: {tags}")
    return lines
