"""Profit-oriented recommendations from live scan artifacts (no auto code edits).

Reads ``reports/latest.json`` and ``config/settings.json``, combines with
``dial_in_analyst`` heuristics, and emits approval-ready suggestions for the
dashboard. Structural repairs stay in ``raydium_doctor.py`` (optional --heal).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from raydium_lp1 import dial_in_analyst, data_provenance, mode_toggle
from raydium_lp1.settings_io import load_settings_json

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_LATEST = REPO / "reports" / "latest.json"
DEFAULT_SETTINGS = REPO / "config" / "settings.json"
DEFAULT_OUT = REPO / "reports" / "doctor_report.json"

OBJECTIVE = (
    "Maximize sustainable LP fee capture: high reported APR with provable exit "
    "routes to SOL/USDC and TVL that survives your exit-safety floor."
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _wallet_runtime() -> dict[str, Any]:
    try:
        from raydium_lp1 import wallet as wallet_mod
        from raydium_lp1.scanner import load_dotenv

        load_dotenv()
        w = wallet_mod.load_wallet()
    except Exception as exc:
        return {"configured": False, "error": str(exc)}

    if w is None:
        settings = _read_json(DEFAULT_SETTINGS) or {}
        addr = str(settings.get("wallet_address") or "").strip()
        if addr:
            return {
                "configured": True,
                "address": addr,
                "source": "settings.json:wallet_address",
                "has_private_key": False,
            }
        return {
            "configured": False,
            "hint": "Set WALLET_ADDRESS in .env or wallet_address in config/settings.json",
        }
    return {
        "configured": True,
        "address": w.address,
        "source": w.source,
        "has_private_key": bool(w.private_key),
    }


def _recommendations_from_scan(report: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    diag = report.get("scan_diagnosis") or {}
    for idx, pressure in enumerate(diag.get("setting_pressure") or []):
        if not isinstance(pressure, dict):
            continue
        recs.append(
            {
                "id": f"dial_in_{pressure.get('setting_key', idx)}",
                "kind": "filter_tune",
                "title": f"Adjust {pressure.get('setting_key')}",
                "detail": pressure.get("concrete_suggestion") or pressure.get("rationale", ""),
                "risk": pressure.get("risk_if_changed", "medium"),
                "requires_approval": True,
                "suggested_direction": pressure.get("direction"),
                "reject_share_pct": pressure.get("reject_share_pct"),
            }
        )

    cand = int(report.get("candidate_count") or 0)
    rej = int(report.get("rejected_count") or 0)
    if cand == 0 and rej > 50:
        top = (diag.get("dominant_reject_drivers") or [{}])[0]
        label = top.get("human_label") or dial_in_analyst.category_label(
            str(top.get("category", "unknown"))
        )
        recs.insert(
            0,
            {
                "id": "zero_candidates_funnel",
                "kind": "strategy",
                "title": "Funnel is closed — loosen one gate",
                "detail": (
                    f"Last pass: 0 candidates / {rej} rejects. Biggest bucket: {label}. "
                    "Change only one of min_apr, min_liquidity_usd, hard_exit_min_tvl_usd, "
                    "or require_sell_route per cycle, then compare reports/rejections.csv."
                ),
                "risk": "high",
                "requires_approval": True,
            },
        )

    if not settings.get("write_rejections"):
        recs.append(
            {
                "id": "enable_rejections_csv",
                "kind": "ops",
                "title": "Enable rejections CSV export",
                "detail": "Set write_rejections=true to log every reject reason to reports/rejections.csv for tuning.",
                "risk": "low",
                "requires_approval": True,
                "settings_patch": {"write_rejections": True},
            }
        )

    rpcs = settings.get("solana_rpc_urls") or []
    if not rpcs:
        recs.append(
            {
                "id": "configure_rpc",
                "kind": "infra",
                "title": "Add Solana RPC URLs",
                "detail": "Wallet balance, pool verify, and route probes need at least one mainnet RPC in settings or .env.",
                "risk": "low",
                "requires_approval": True,
            }
        )

    mode = mode_toggle.get_mode()
    if mode == "live" and not _wallet_runtime().get("has_private_key"):
        recs.append(
            {
                "id": "live_without_signer",
                "kind": "safety",
                "title": "LIVE mode without signing key",
                "detail": (
                    "Mode is LIVE but no WALLET_PRIVATE_KEY / keypair path is configured. "
                    "Scans can run; swaps/LP opens will fail until a signer is present."
                ),
                "risk": "critical",
                "requires_approval": False,
            }
        )

    return recs[:12]


def build_doctor_report(
    *,
    latest_path: Path = DEFAULT_LATEST,
    settings_path: Path = DEFAULT_SETTINGS,
    include_structural: bool = False,
    heal: bool | None = None,
) -> dict[str, Any]:
    from raydium_lp1.doctor_heal_policy import should_auto_heal

    if heal is None:
        heal = should_auto_heal()
    settings: dict[str, Any] = {}
    try:
        settings = load_settings_json(settings_path)
    except (OSError, ValueError) as exc:
        settings = {"_load_error": str(exc)}

    report = _read_json(latest_path) or {}
    structural: dict[str, Any] | None = None
    if include_structural:
        from raydium_lp1 import raydium_doctor

        results = raydium_doctor.run_checks(heal=heal)
        structural = raydium_doctor.summarize(results)

    mode = mode_toggle.get_mode()
    wallet = _wallet_runtime()
    provenance = report.get("data_provenance")
    if not provenance and report:
        try:
            from raydium_lp1.scanner import ScannerConfig

            cfg = ScannerConfig.from_file(settings_path)
            provenance = data_provenance.build_provenance(config=cfg)
        except Exception:
            provenance = {"non_live_components": data_provenance.NON_LIVE_COMPONENTS}

    recommendations = _recommendations_from_scan(report, settings)
    narrative = (report.get("scan_diagnosis") or {}).get("narrative_lines") or []

    return {
        "generated_at": _now_iso(),
        "objective": OBJECTIVE,
        "mode": mode,
        "dry_run": bool(settings.get("dry_run", mode == "demo")),
        "wallet": wallet,
        "data_sources": {
            "scanner_pool_list": "LIVE — Raydium api-v3 /pools/info/list",
            "sell_routes": "LIVE — Jupiter v6 quote + Raydium compute (when require_sell_route)",
            "wallet_balance": "LIVE — Solana RPC getBalance when wallet + RPC configured",
            "dial_in_suggestions": "MODELED — rejection histogram heuristics",
            "trade_execution": (
                "LIVE boundary — on-chain spends only when mode=live AND trade runner calls require_live()"
            ),
            "provenance": provenance,
        },
        "last_scan": {
            "scanned_at": report.get("scanned_at"),
            "scanned_count": report.get("scanned_count"),
            "candidate_count": report.get("candidate_count"),
            "rejected_count": report.get("rejected_count"),
            "rejection_breakdown": report.get("rejection_breakdown"),
        },
        "narrative_lines": narrative,
        "recommendations": recommendations,
        "structural_health": structural,
    }


def write_doctor_report(path: Path = DEFAULT_OUT, **kwargs: Any) -> Path:
    payload = build_doctor_report(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
