"""Rules for manual LIVE CLMM opens (explicit pool id via CLI or dashboard)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from raydium_lp1 import routes
from raydium_lp1.lp_pay_mint import PayMintResolution, resolve_pay_mint

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_ALERTS_PATH = REPO / "reports" / "manual_live_alerts.json"


class ManualLiveBlockedError(RuntimeError):
    """Manual LIVE open rejected before signing (liquidity / route / policy)."""

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


def manual_live_alerts_path(config: Any | None = None) -> Path:
    if config is None:
        return DEFAULT_ALERTS_PATH
    raw = str(getattr(config, "manual_live_alerts_path", "") or "").strip()
    return Path(raw) if raw else DEFAULT_ALERTS_PATH


def _alt_token(pool: Mapping[str, Any], pay_res: PayMintResolution | None) -> tuple[str, str]:
    if pay_res is not None:
        return pay_res.alt_symbol, pay_res.alt_mint
    a_sym = str(pool.get("mint_a_symbol") or "")
    b_sym = str(pool.get("mint_b_symbol") or "")
    return a_sym, str(pool.get("mint_a") or "")


def notify_manual_live_blocked(
    reason: str,
    pool: Mapping[str, Any],
    *,
    config: Any | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Append alert and return path written."""

    path = manual_live_alerts_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                rows = [dict(x) for x in raw if isinstance(x, dict)]
            elif isinstance(raw, dict):
                rows = [dict(x) for x in (raw.get("alerts") or []) if isinstance(x, dict)]
        except (OSError, json.JSONDecodeError):
            rows = []
    entry = {
        "at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "liquidity_usd": pool.get("liquidity_usd"),
        "apr": pool.get("apr"),
        **(dict(extra) if extra else {}),
    }
    rows.append(entry)
    rows = rows[-100:]
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return path


def assert_manual_live_open_allowed(
    pool: Mapping[str, Any],
    config: Any,
    *,
    explicit_pool_id: bool = True,
) -> dict[str, Any]:
    """Raise :class:`ManualLiveBlockedError` and notify if manual-open policy fails."""

    if not explicit_pool_id:
        return {"ok": True, "skipped": True, "reason": "not_explicit_pool_id"}

    min_liq = float(getattr(config, "manual_live_min_pool_liquidity_usd", 1000.0) or 1000.0)
    liq = float(pool.get("liquidity_usd") or 0.0)
    pair = f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}"
    pid = str(pool.get("id") or "")

    if liq < min_liq:
        reason = (
            f"Manual LIVE blocked: pool TVL ${liq:,.2f} is below "
            f"manual_live_min_pool_liquidity_usd ${min_liq:,.2f} ({pair})."
        )
        alert_path = notify_manual_live_blocked(
            reason,
            pool,
            config=config,
            extra={"rule": "min_pool_liquidity", "required_usd": min_liq},
        )
        raise ManualLiveBlockedError(
            reason,
            detail={
                "rule": "min_pool_liquidity",
                "liquidity_usd": liq,
                "required_usd": min_liq,
                "alert_path": str(alert_path),
                "pool_id": pid,
            },
        )

    if bool(getattr(config, "manual_live_require_sell_route", True)):
        impact = float(getattr(config, "manual_live_max_route_price_impact_pct", 0) or 0)
        if impact <= 0:
            impact = float(getattr(config, "max_route_price_impact_pct", 5.0) or 5.0)
        sell = routes.check_pool_sellability(
            dict(pool),
            base_symbols=tuple(s.upper() for s in sorted(getattr(config, "allowed_quote_symbols", ()) or ("SOL", "USDC", "USDT"))),
            sources=getattr(config, "route_sources", ("jupiter", "raydium")),
            max_route_price_impact_pct=impact,
        )
        pay_res = resolve_pay_mint(pool, config)
        alt_sym, alt_mint = _alt_token(pool, pay_res)
        if pay_res:
            alt_check = sell.token_b if pay_res.pay_is_mint_a else sell.token_a
            route_ok = alt_check.ok
            route_reasons = sell.reasons if not alt_check.ok else []
        else:
            route_ok = sell.ok
            route_reasons = sell.reasons

        if not route_ok:
            reason = (
                f"Manual LIVE blocked: no sell route for alt token {alt_sym or alt_mint[:8]} "
                f"in {pair} (require_sell_route). "
                + "; ".join(route_reasons[:3])
            )
            alert_path = notify_manual_live_blocked(
                reason,
                pool,
                config=config,
                extra={"rule": "sell_route", "alt_symbol": alt_sym, "sellability": sell.to_dict()},
            )
            raise ManualLiveBlockedError(
                reason,
                detail={
                    "rule": "sell_route",
                    "alert_path": str(alert_path),
                    "sellability": sell.to_dict(),
                    "pool_id": pid,
                },
            )

    return {
        "ok": True,
        "liquidity_usd": liq,
        "min_pool_liquidity_usd": min_liq,
        "sell_route_checked": bool(getattr(config, "manual_live_require_sell_route", True)),
    }
