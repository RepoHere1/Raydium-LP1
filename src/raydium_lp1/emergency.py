"""Emergency close logic for Raydium-LP1.

When a position's pool turns ``critical`` we want to bail. This module:

* Detects critical pools coming out of the health monitor.
* Builds a dry-run swap-back plan (token -> base via Jupiter) capped at the
  configured max slippage.
* Emits alerts to the console and appends them to ``reports/alerts.json``.

Nothing here signs or sends real transactions. The swap-build path is
designed so feature work can later swap ``simulate=True`` for actual
execution once the user lifts the dry-run gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode

from raydium_lp1 import health, routes

DEFAULT_ALERTS_PATH = Path("reports/alerts.json")
DEFAULT_MAX_SLIPPAGE_PCT = 0.30  # 30%
JUPITER_SWAP_URL = "https://quote-api.jup.ag/v6/swap"
JUPITER_QUOTE_URL = routes.JUPITER_QUOTE_URL

BASE_TOKENS = routes.BASE_TOKENS


@dataclass
class SwapPlan:
    """A dry-run description of the swap we WOULD send."""

    input_mint: str
    input_symbol: str
    output_mint: str
    output_symbol: str
    amount: int
    slippage_bps: int
    quote_url: str
    swap_url: str
    dry_run: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "input_mint": self.input_mint,
            "input_symbol": self.input_symbol,
            "output_mint": self.output_mint,
            "output_symbol": self.output_symbol,
            "amount": self.amount,
            "slippage_bps": self.slippage_bps,
            "quote_url": self.quote_url,
            "swap_url": self.swap_url,
            "dry_run": self.dry_run,
            "notes": list(self.notes),
        }


@dataclass
class Alert:
    timestamp: str
    pool_id: str
    pair: str
    severity: str
    reasons: list[str]
    health: dict
    swap_plans: list[dict]
    action: str = "would_swap_to_base"
    dry_run: bool = True

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "pool_id": self.pool_id,
            "pair": self.pair,
            "severity": self.severity,
            "reasons": list(self.reasons),
            "health": dict(self.health),
            "swap_plans": list(self.swap_plans),
            "action": self.action,
            "dry_run": self.dry_run,
        }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_swap_plan(
    token_mint: str,
    token_symbol: str,
    amount: int,
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = DEFAULT_MAX_SLIPPAGE_PCT,
) -> SwapPlan:
    """Construct a Jupiter swap-back plan WITHOUT executing it.

    ``amount`` is in input-token base units. ``max_slippage_pct`` of 0.30
    means "tolerate up to 30% slippage". We translate to basis points for
    the Jupiter API URL.
    """

    base_symbol_upper = base_symbol.upper()
    output_mint = BASE_TOKENS.get(base_symbol_upper, BASE_TOKENS["SOL"])
    slippage_bps = max(1, int(round(max_slippage_pct * 10_000)))
    params = {
        "inputMint": token_mint,
        "outputMint": output_mint,
        "amount": amount,
        "slippageBps": slippage_bps,
        "swapMode": "ExactIn",
    }
    quote_url = f"{JUPITER_QUOTE_URL}?{urlencode(params)}"
    notes = [
        "DRY-RUN: this plan describes the request we WOULD send to Jupiter.",
        f"Max slippage: {max_slippage_pct * 100:.0f}% ({slippage_bps} bps).",
        "Execution path: GET quote -> POST /v6/swap with user wallet pubkey -> sign -> send.",
        "No signing or send is performed in this build.",
    ]
    return SwapPlan(
        input_mint=token_mint,
        input_symbol=(token_symbol or "").upper(),
        output_mint=output_mint,
        output_symbol=base_symbol_upper,
        amount=amount,
        slippage_bps=slippage_bps,
        quote_url=quote_url,
        swap_url=JUPITER_SWAP_URL,
        dry_run=True,
        notes=notes,
    )


def plan_emergency_close(
    pool: dict,
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = DEFAULT_MAX_SLIPPAGE_PCT,
    position_token_amount: int = 1_000_000,
) -> list[SwapPlan]:
    """Build swap plans for BOTH sides of a pool position.

    For a real position the caller would pass the actual amount-out of LP
    burn for each side; here we use a placeholder ``position_token_amount``
    (1 token at 6 decimals) so the plan is well-formed in dry-run.
    """

    plans: list[SwapPlan] = []
    for side_letter in ("a", "b"):
        mint = pool.get(f"mint_{side_letter}", "")
        symbol = pool.get(f"mint_{side_letter}_symbol", "")
        if not mint:
            continue
        if (symbol or "").upper() == base_symbol.upper():
            continue
        plans.append(
            build_swap_plan(
                mint,
                symbol,
                position_token_amount,
                base_symbol=base_symbol,
                max_slippage_pct=max_slippage_pct,
            )
        )
    return plans


def build_alert(
    pool: dict,
    assessment: health.HealthAssessment,
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = DEFAULT_MAX_SLIPPAGE_PCT,
    now_iso: str | None = None,
) -> Alert:
    swap_plans = plan_emergency_close(
        pool,
        base_symbol=base_symbol,
        max_slippage_pct=max_slippage_pct,
    )
    pair = f"{pool.get('mint_a_symbol', '')}/{pool.get('mint_b_symbol', '')}"
    return Alert(
        timestamp=now_iso or _now_iso(),
        pool_id=str(pool.get("id", "")),
        pair=pair,
        severity=assessment.score,
        reasons=list(assessment.reasons),
        health=assessment.to_dict(),
        swap_plans=[plan.to_dict() for plan in swap_plans],
        action="would_swap_to_base",
        dry_run=True,
    )


def load_alerts(path: Path = DEFAULT_ALERTS_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("alerts"), list):
        return data["alerts"]
    return []


def append_alerts(alerts: Iterable[Alert], path: Path = DEFAULT_ALERTS_PATH, *, max_kept: int = 500) -> list[dict]:
    """Append new alerts to the on-disk alerts file (keeps newest ``max_kept``)."""

    existing = load_alerts(path)
    new_dicts = [a.to_dict() for a in alerts]
    combined = existing + new_dicts
    if max_kept > 0 and len(combined) > max_kept:
        combined = combined[-max_kept:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return combined


def format_alert_console(alert: Alert) -> str:
    """Human-friendly one-block alert print."""

    lines = [
        f"!! EMERGENCY {alert.severity.upper()} | {alert.pair} | pool={alert.pool_id}",
        f"   time: {alert.timestamp}",
    ]
    for reason in alert.reasons:
        lines.append(f"   - {reason}")
    lines.append(f"   action (dry-run): {alert.action}")
    for plan in alert.swap_plans:
        lines.append(
            f"   would swap: {plan['input_symbol'] or plan['input_mint'][:6]}"
            f" -> {plan['output_symbol']}"
            f" (slippage {plan['slippage_bps']/100:.1f}%)"
        )
    if alert.dry_run:
        lines.append("   DRY-RUN: nothing executed, nothing signed.")
    return "\n".join(lines)


def run_emergency_pass(
    pools_with_assessments: Iterable[tuple[dict, health.HealthAssessment]],
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = DEFAULT_MAX_SLIPPAGE_PCT,
    alerts_path: Path = DEFAULT_ALERTS_PATH,
    printer: Callable[[str], None] | None = print,
    now_iso: str | None = None,
) -> list[Alert]:
    """Iterate (pool, assessment) pairs, alert on critical ones, persist."""

    triggered: list[Alert] = []
    for pool, assessment in pools_with_assessments:
        if assessment.score != health.HEALTH_CRITICAL:
            continue
        alert = build_alert(
            pool,
            assessment,
            base_symbol=base_symbol,
            max_slippage_pct=max_slippage_pct,
            now_iso=now_iso,
        )
        triggered.append(alert)
        if printer is not None:
            printer(format_alert_console(alert))
    if triggered:
        append_alerts(triggered, alerts_path)
    return triggered
