"""Route watchdog: probe open LP alt tokens 5× per 24h; emergency close on sketchy 5th check.

Human-cycle leniency: during typical global low-trader hours (weekends + 22:00–08:00 UTC),
soft route degradation (high impact, flaky APIs) does not count toward emergency unless
routes are fully dead or prior checks were repeatedly sketchy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from raydium_lp1 import routes
from raydium_lp1.lp_pay_mint import resolve_pay_mint

REPO = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = REPO / "reports" / "emergency_route_watch.json"
WINDOW_HOURS = 24


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


def is_low_human_activity(now: datetime | None = None) -> bool:
    """True when global spot/crypto flow is often thinner (sleep / weekend)."""

    t = now or _now()
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    else:
        t = t.astimezone(UTC)
    if t.weekday() >= 5:
        return True
    hour = t.hour
    return hour >= 22 or hour < 8


@dataclass
class RouteProbeResult:
    ok: bool
    sketchy: bool
    hard_sketchy: bool
    reasons: list[str]
    pay_symbol: str
    alt_mint: str
    alt_symbol: str
    sellability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "sketchy": self.sketchy,
            "hard_sketchy": self.hard_sketchy,
            "reasons": list(self.reasons),
            "pay_symbol": self.pay_symbol,
            "alt_mint": self.alt_mint,
            "alt_symbol": self.alt_symbol,
            "sellability": dict(self.sellability),
        }


def classify_route_probe(
    sell: routes.SellabilityResult,
    *,
    low_activity: bool,
    max_impact_pct: float = 30.0,
) -> tuple[bool, bool, list[str]]:
    """Return (sketchy, hard_sketchy, reasons)."""

    reasons: list[str] = []
    hard = False
    for label, check in (("A", sell.token_a), ("B", sell.token_b)):
        if check.ok:
            continue
        msg = f"no sell route for token {label} ({check.token_symbol or check.token_mint[:8]})"
        reasons.append(msg)
        hard = True
        for rec in check.sources:
            if rec.get("impact_reject"):
                reasons.append(str(rec.get("error") or "price impact reject"))
                hard = True
    if not reasons:
        return False, False, []
    if low_activity and not hard:
        soft_only = all("no sell route" not in r for r in reasons)
        if soft_only:
            return False, False, []
    if low_activity and hard:
        return True, True, reasons
    return True, hard, reasons


def probe_position_routes(
    pool: Mapping[str, Any],
    *,
    config: Any | None = None,
    max_route_price_impact_pct: float = 0.0,
    now: datetime | None = None,
) -> RouteProbeResult | None:
    pay = resolve_pay_mint(pool, config)
    if pay is None:
        return None
    low = is_low_human_activity(now)
    sell = routes.check_pool_sellability(
        pool,
        max_route_price_impact_pct=max_route_price_impact_pct,
    )
    sketchy, hard, reasons = classify_route_probe(
        sell,
        low_activity=low,
        max_impact_pct=float(getattr(config, "max_route_price_impact_pct", 30) or 30),
    )
    return RouteProbeResult(
        ok=not sketchy,
        sketchy=sketchy,
        hard_sketchy=hard,
        reasons=reasons,
        pay_symbol=pay.pay_symbol,
        alt_mint=pay.alt_mint,
        alt_symbol=pay.alt_symbol,
        sellability=sell.to_dict(),
    )


def load_watch_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if not path.is_file():
        return {"positions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"positions": {}}
    if not isinstance(data, dict):
        return {"positions": {}}
    data.setdefault("positions", {})
    return data


def save_watch_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _prune_checks(checks: list[dict], *, now: datetime, window_hours: float) -> list[dict]:
    cutoff = now - timedelta(hours=window_hours)
    out: list[dict] = []
    for row in checks:
        if not isinstance(row, dict):
            continue
        ts = row.get("ts")
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            continue
        if dt >= cutoff:
            out.append(row)
    return out


def should_emergency_close_on_check(
    checks_in_window: list[dict],
    *,
    current_sketchy: bool,
    current_hard: bool,
    low_activity: bool,
    checks_per_day: int = 5,
) -> tuple[bool, str]:
    """After recording current check, decide if we fire emergency close."""

    n = len(checks_in_window)
    if n < checks_per_day or not current_sketchy:
        return False, f"checks={n}/{checks_per_day} sketchy={current_sketchy}"
    sketchy_count = sum(1 for c in checks_in_window if c.get("sketchy"))
    if not low_activity:
        return True, f"check #{n} sketchy during active hours ({sketchy_count}/{checks_per_day} sketchy)"
    if current_hard:
        return True, f"check #{n} hard unsellable during low-activity hours"
    if sketchy_count >= max(3, checks_per_day - 1):
        return True, f"check #{n} with {sketchy_count}/{checks_per_day} sketchy during low-activity"
    return False, f"low-activity leniency: {sketchy_count}/{checks_per_day} sketchy, not hard"


def record_route_check(
    state: dict[str, Any],
    *,
    position_nft_mint: str,
    pool_id: str,
    pair: str,
    probe: RouteProbeResult,
    low_activity: bool,
    checks_per_day: int = 5,
    now: datetime | None = None,
) -> tuple[list[dict], bool, str]:
    now = now or _now()
    positions = state.setdefault("positions", {})
    row = positions.setdefault(
        position_nft_mint,
        {"pool_id": pool_id, "pair": pair, "checks": []},
    )
    row["pool_id"] = pool_id
    row["pair"] = pair
    checks = _prune_checks(list(row.get("checks") or []), now=now, window_hours=WINDOW_HOURS)
    check_num = len(checks) + 1
    checks.append(
        {
            "ts": _now_iso(),
            "check_num": check_num,
            "sketchy": probe.sketchy,
            "hard_sketchy": probe.hard_sketchy,
            "low_activity": low_activity,
            "reasons": list(probe.reasons),
        }
    )
    checks = _prune_checks(checks, now=now, window_hours=WINDOW_HOURS)
    row["checks"] = checks
    fire, reason = should_emergency_close_on_check(
        checks,
        current_sketchy=probe.sketchy,
        current_hard=probe.hard_sketchy,
        low_activity=low_activity,
        checks_per_day=checks_per_day,
    )
    return checks, fire, reason


def min_interval_seconds(checks_per_day: int = 5, window_hours: float = WINDOW_HOURS) -> float:
    per_day = max(1, int(checks_per_day))
    return (window_hours * 3600.0) / per_day


def due_for_probe(last_ts: str | None, *, checks_per_day: int = 5) -> bool:
    if not last_ts:
        return True
    try:
        dt = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return True
    elapsed = (_now() - dt.astimezone(UTC)).total_seconds()
    return elapsed >= min_interval_seconds(checks_per_day) * 0.95


def list_wallet_clmm_positions() -> list[dict[str, Any]]:
    from raydium_lp1.raydium_clmm import _run_script

    chain = _run_script("list_owner_positions.mjs", {}, timeout=120.0)
    if not chain.get("ok"):
        return []
    return [p for p in (chain.get("positions") or []) if int(p.get("liquidity") or 0) > 0]


def run_route_watch_pass(
    *,
    config: Any,
    execute_live: bool | None = None,
    state_path: Path | None = None,
    alerts_path: Path | None = None,
    pool_fetcher: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    """Probe each open position; optionally execute emergency close + pay sweep."""

    from raydium_lp1 import emergency
    from raydium_lp1 import mode_toggle

    state_path = state_path or Path(
        getattr(config, "emergency_route_watch_state_path", None) or DEFAULT_STATE_PATH
    )
    alerts_path = alerts_path or Path(getattr(config, "emergency_alerts_path", "reports/alerts.json"))
    checks_per_day = max(1, int(getattr(config, "emergency_route_checks_per_day", 5) or 5))
    if execute_live is None:
        execute_live = mode_toggle.get_mode() == "live"

    state = load_watch_state(state_path)
    positions = list_wallet_clmm_positions()
    results: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []

    if pool_fetcher is None:
        from raydium_lp1.lp_selection import fetch_pool_by_id

        def _fetch(pid: str) -> dict:
            return fetch_pool_by_id(pid, config=config)

        pool_fetcher = _fetch

    for pos in positions:
        nft = str(pos.get("position_nft_mint") or "")
        pool_id = str(pos.get("pool_id") or "")
        if not nft or not pool_id:
            continue
        prev = (state.get("positions") or {}).get(nft) or {}
        prev_checks = prev.get("checks") or []
        last_ts = prev_checks[-1].get("ts") if prev_checks else None
        if not due_for_probe(last_ts, checks_per_day=checks_per_day):
            results.append({"nft": nft, "pool_id": pool_id, "skipped": True, "reason": "interval_not_due"})
            continue
        try:
            pool = pool_fetcher(pool_id)
        except Exception as exc:
            results.append({"nft": nft, "pool_id": pool_id, "error": str(exc)})
            continue
        pair = f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}"
        low = is_low_human_activity()
        probe = probe_position_routes(
            pool,
            config=config,
            max_route_price_impact_pct=float(getattr(config, "max_route_price_impact_pct", 0) or 0),
        )
        if probe is None:
            results.append({"nft": nft, "pool_id": pool_id, "error": "no pay leg resolved"})
            continue
        checks, fire, close_reason = record_route_check(
            state,
            position_nft_mint=nft,
            pool_id=pool_id,
            pair=pair,
            probe=probe,
            low_activity=low,
            checks_per_day=checks_per_day,
        )
        row = {
            "nft": nft,
            "pool_id": pool_id,
            "pair": pair,
            "probe": probe.to_dict(),
            "checks_in_window": len(checks),
            "low_human_activity": low,
            "emergency_close": fire,
            "close_reason": close_reason,
        }
        if fire and execute_live and bool(getattr(config, "emergency_close_enabled", True)):
            ex = emergency.execute_emergency_route_close(
                nft,
                pool,
                config=config,
                reason=close_reason,
                probe=probe.to_dict(),
                check_number=len(checks),
                low_human_activity=low,
                alerts_path=alerts_path,
            )
            row["execution"] = ex
            if ex.get("ok"):
                executed.append(row)
                state.get("positions", {}).pop(nft, None)
        results.append(row)

    save_watch_state(state, state_path)
    return {
        "ok": True,
        "probed": len(results),
        "executed_count": len(executed),
        "results": results,
        "executed": executed,
        "state_path": str(state_path),
    }
