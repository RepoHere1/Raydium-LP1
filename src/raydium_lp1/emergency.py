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
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from raydium_lp1 import health, robust_routes, routes

DEFAULT_ALERTS_PATH = Path("reports/alerts.json")
DEFAULT_MAX_SLIPPAGE_PCT = 0.30  # 30%
JUPITER_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"
JUPITER_QUOTE_URLS = routes.JUPITER_QUOTE_URLS
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
    use_robust_routing: bool = False,
    fetcher: Callable[[str], dict] | None = None,
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

    best_source: str | None = None
    best_out_amount: float | None = None
    route_quality: dict | None = None
    if use_robust_routing:
        best = robust_routes.best_route(
            token_mint,
            output_mint,
            amount=amount,
            slippage_bps=slippage_bps,
            fetcher=fetcher,
        )
        best_source = best.best_source
        best_out_amount = best.best_out_amount
        route_quality = best.quality
        if best_source:
            notes.append(
                f"Best route source (via robust router): {best_source} (out={best_out_amount})."
            )
            notes.append(robust_routes.log_route_quality(best))

    plan = SwapPlan(
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
    if route_quality is not None:
        plan.notes.append(f"route_quality_metrics={route_quality}")
    return plan


def plan_emergency_close(
    pool: dict,
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = DEFAULT_MAX_SLIPPAGE_PCT,
    position_token_amount: int = 1_000_000,
    use_robust_routing: bool = False,
    fetcher: Callable[[str], dict] | None = None,
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
                use_robust_routing=use_robust_routing,
                fetcher=fetcher,
            )
        )
    return plans


def build_alert(
    pool: dict,
    assessment: health.HealthAssessment,
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = DEFAULT_MAX_SLIPPAGE_PCT,
    use_robust_routing: bool = False,
    fetcher: Callable[[str], dict] | None = None,
    now_iso: str | None = None,
) -> Alert:
    swap_plans = plan_emergency_close(
        pool,
        base_symbol=base_symbol,
        max_slippage_pct=max_slippage_pct,
        use_robust_routing=use_robust_routing,
        fetcher=fetcher,
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


def latest_emergency_close_banner(alerts_path: Path = DEFAULT_ALERTS_PATH) -> dict[str, Any] | None:
    """Most recent executed emergency close for dashboard banner."""

    for row in reversed(load_alerts(alerts_path)):
        if not isinstance(row, dict):
            continue
        if row.get("type") == "emergency_close_executed" or row.get("action") == "emergency_close_executed":
            return {
                "headline": "EMERGENCY CLOSE",
                "reason": str(row.get("reason") or row.get("close_reason") or ""),
                "pair": str(row.get("pair") or ""),
                "pool_id": str(row.get("pool_id") or ""),
                "position_nft_mint": str(row.get("position_nft_mint") or ""),
                "timestamp": str(row.get("timestamp") or ""),
            }
    return None


def append_emergency_close_alert(
    *,
    pool_id: str,
    pair: str,
    position_nft_mint: str,
    reason: str,
    check_number: int,
    low_human_activity: bool,
    execution: dict[str, Any],
    alerts_path: Path = DEFAULT_ALERTS_PATH,
) -> dict[str, Any]:
    alert = {
        "type": "emergency_close_executed",
        "action": "emergency_close_executed",
        "timestamp": _now_iso(),
        "pool_id": pool_id,
        "pair": pair,
        "position_nft_mint": position_nft_mint,
        "reason": reason,
        "check_number": check_number,
        "low_human_activity": low_human_activity,
        "execution": execution,
        "dry_run": False,
    }
    existing = load_alerts(alerts_path)
    existing.append(alert)
    if len(existing) > 500:
        existing = existing[-500:]
    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    alerts_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return alert


def execute_emergency_route_close(
    position_nft_mint: str,
    pool: dict,
    *,
    config: Any,
    reason: str,
    probe: dict[str, Any] | None = None,
    check_number: int = 5,
    low_human_activity: bool = False,
    alerts_path: Path | None = None,
) -> dict[str, Any]:
    """LIVE: close CLMM NFT, burn if needed, swap alt balance → pool pay token."""

    from raydium_lp1.lp_order_rules import close_clmm_position
    from raydium_lp1.lp_pay_mint import resolve_pay_mint
    from raydium_lp1.live_guard import guard_onchain
    from raydium_lp1.mode_toggle import ModeBlockedError

    alerts_path = alerts_path or Path(getattr(config, "emergency_alerts_path", DEFAULT_ALERTS_PATH))
    pair = f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}"
    out: dict[str, Any] = {
        "ok": False,
        "position_nft_mint": position_nft_mint,
        "pool_id": str(pool.get("id") or ""),
        "pair": pair,
        "reason": reason,
    }
    try:
        guard_onchain(f"emergency route close {pair}")
    except ModeBlockedError as exc:
        out["error"] = str(exc)
        return out

    pay = resolve_pay_mint(pool, config)
    if pay is None:
        out["error"] = "no pay leg for emergency sweep"
        return out

    try:
        close_result = close_clmm_position(position_nft_mint, config=config, timeout=180.0)
    except Exception as exc:
        out["error"] = f"close failed: {exc}"
        return out
    out["close"] = close_result
    if not close_result.get("ok"):
        out["error"] = close_result.get("error") or "close returned not ok"
        return out

    swap_result = _swap_wallet_alt_to_pay(
        pay.alt_mint,
        pay.pay_mint,
        pay.pay_symbol,
        max_slippage_pct=float(getattr(config, "emergency_max_slippage_pct", 0.30) or 0.30),
    )
    out["alt_to_pay_swap"] = swap_result
    out["ok"] = True
    out["probe"] = probe
    append_emergency_close_alert(
        pool_id=str(pool.get("id") or ""),
        pair=pair,
        position_nft_mint=position_nft_mint,
        reason=reason,
        check_number=check_number,
        low_human_activity=low_human_activity,
        execution=out,
        alerts_path=alerts_path,
    )
    return out


def _swap_wallet_alt_to_pay(
    alt_mint: str,
    pay_mint: str,
    pay_symbol: str,
    *,
    max_slippage_pct: float = 0.30,
) -> dict[str, Any]:
    """Swap full wallet balance of alt mint → pay mint via Jupiter lite-api."""

    import base64
    import os
    import urllib.parse
    import urllib.request

    from solders.keypair import Keypair
    from solders.message import to_bytes_versioned
    from solders.transaction import VersionedTransaction

    from raydium_lp1.fee_guard import cap_priority_micro, fee_config_from_settings
    from raydium_lp1.scanner import load_dotenv

    load_dotenv()
    kp_path = os.environ.get("SOLANA_KEYPAIR_PATH", "").strip()
    if not kp_path:
        return {"ok": False, "skipped": True, "reason": "no keypair"}
    kp = Keypair.from_bytes(bytes(json.loads(Path(kp_path).expanduser().read_text(encoding="utf-8"))))
    owner = str(kp.pubkey())
    rpc = (
        os.environ.get("SOLANA_RPC_URL", "").strip()
        or "https://api.mainnet-beta.solana.com"
    )

    def _rpc(method: str, params: list) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode())
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload.get("result") or {}

    bal = _rpc(
        "getTokenAccountsByOwner",
        [owner, {"mint": alt_mint}, {"encoding": "jsonParsed"}],
    )
    amount_raw = 0
    for acct in bal.get("value") or []:
        info = (acct.get("account") or {}).get("data", {}).get("parsed", {}).get("info", {})
        amt = info.get("tokenAmount") or {}
        amount_raw += int(amt.get("amount") or 0)
    if amount_raw <= 0:
        return {"ok": True, "skipped": True, "reason": "zero alt balance after close"}

    slippage_bps = max(1, int(round(max_slippage_pct * 10_000)))
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://jup.ag",
    }
    quote = None
    quote_url = ""
    for base in JUPITER_QUOTE_URLS:
        qs = urllib.parse.urlencode(
            {
                "inputMint": alt_mint,
                "outputMint": pay_mint,
                "amount": str(amount_raw),
                "slippageBps": str(slippage_bps),
                "swapMode": "ExactIn",
            }
        )
        quote_url = f"{base}?{qs}"
        try:
            req = urllib.request.Request(quote_url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                quote = json.loads(resp.read().decode())
            if quote and not quote.get("error"):
                break
        except (OSError, json.JSONDecodeError):
            quote = None
    if not quote or quote.get("error"):
        return {"ok": False, "error": "no Jupiter quote alt→pay", "url": quote_url}

    fee_cfg = fee_config_from_settings()
    pri = cap_priority_micro(None, fee_cfg)
    swap_body = json.dumps(
        {
            "quoteResponse": quote,
            "userPublicKey": owner,
            "wrapAndUnwrapSol": True,
            "asLegacyTransaction": False,
            "computeUnitPriceMicroLamports": pri,
        }
    ).encode()
    req = urllib.request.Request(
        JUPITER_SWAP_URL,
        data=swap_body,
        headers={**headers, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        swap_payload = json.loads(resp.read().decode())
    tx_b64 = swap_payload.get("swapTransaction")
    if not tx_b64:
        return {"ok": False, "error": "swap build failed", "detail": swap_payload}
    raw_tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    signed = VersionedTransaction.populate(
        raw_tx.message,
        [kp.sign_message(to_bytes_versioned(raw_tx.message))],
    )
    sig = _rpc(
        "sendTransaction",
        [base64.b64encode(bytes(signed)).decode(), {"encoding": "base64", "skipPreflight": False}],
    )
    if isinstance(sig, str):
        return {
            "ok": True,
            "signature": sig,
            "input_mint": alt_mint,
            "output_mint": pay_mint,
            "output_symbol": pay_symbol,
            "amount_raw": str(amount_raw),
        }
    return {"ok": False, "error": f"send failed: {sig}"}


def run_emergency_pass(
    pools_with_assessments: Iterable[tuple[dict, health.HealthAssessment]],
    *,
    base_symbol: str = "SOL",
    max_slippage_pct: float = DEFAULT_MAX_SLIPPAGE_PCT,
    alerts_path: Path = DEFAULT_ALERTS_PATH,
    printer: Callable[[str], None] | None = print,
    use_robust_routing: bool = False,
    fetcher: Callable[[str], dict] | None = None,
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
            use_robust_routing=use_robust_routing,
            fetcher=fetcher,
            now_iso=now_iso,
        )
        triggered.append(alert)
        if printer is not None:
            printer(format_alert_console(alert))
    if triggered:
        append_alerts(triggered, alerts_path)
    return triggered
