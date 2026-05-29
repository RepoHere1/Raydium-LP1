"""Actionable tuning plan: map scan diagnosis → settings patches + live readiness."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from raydium_lp1 import dial_in_analyst, mode_toggle
from raydium_lp1.dial_in_analyst import build_scan_diagnosis
from raydium_lp1.scanner import ScannerConfig, load_dotenv
from raydium_lp1.settings_io import load_settings_json, merge_known_settings_patch

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_LATEST = REPO / "reports" / "latest.json"
DEFAULT_SETTINGS = REPO / "config" / "settings.json"


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


def _nice_floor(x: float, floor: float) -> float:
    if x <= floor or not math.isfinite(x):
        return floor
    return float(max(floor, round(x, 2)))


def _pressure_to_patch(pressure: dict[str, Any], config: ScannerConfig) -> dict[str, Any]:
    """Turn one ``setting_pressure`` row into concrete settings.json values."""

    key = str(pressure.get("setting_key") or "")
    direction = str(pressure.get("direction") or "").lower()
    cat = str(pressure.get("category_driver") or "")
    patch: dict[str, Any] = {}

    if key == "pool_sort_field" and direction in ("align_with_apr_feed", "lower", "change"):
        # APR-sorted pages are mostly dust/scam; scan liquidity-ranked CLMM instead.
        patch["pool_sort_field"] = "liquidity"
        patch["sort_type"] = "desc"
        if not config.apr_field:
            patch["apr_field"] = "apr24h"
        return patch

    if key == "min_liquidity_usd" and direction == "lower":
        cur = float(config.min_liquidity_usd)
        nxt = _nice_floor(cur * 0.55, 250.0)
        if nxt < cur:
            patch["min_liquidity_usd"] = nxt
        return patch

    if key == "min_apr" and direction == "lower":
        cur = float(config.min_apr)
        nxt = _nice_floor(cur * 0.65, 25.0)
        if nxt < cur:
            patch["min_apr"] = nxt
        return patch

    if key == "min_volume_24h_usd" and direction == "lower":
        cur = float(config.min_volume_24h_usd)
        nxt = _nice_floor(cur * 0.5, 500.0)
        if nxt < cur:
            patch["min_volume_24h_usd"] = nxt
        return patch

    if key == "hard_exit_min_tvl_usd" and direction == "lower":
        cur = float(config.hard_exit_min_tvl_usd)
        if cur <= 0:
            return patch
        nxt = _nice_floor(cur * 0.7, 50.0)
        if nxt < cur:
            patch["hard_exit_min_tvl_usd"] = nxt
        return patch

    if key == "max_route_price_impact_pct" and direction == "raise":
        cur = float(config.max_route_price_impact_pct or 30.0)
        nxt = min(30.0, cur + 5.0)
        if nxt > cur:
            patch["max_route_price_impact_pct"] = nxt
        return patch

    if cat == "hard_exit_red_line" and key == "hard_exit_min_tvl_usd" and not patch:
        # Fallback when narrative exists but direction omitted.
        cur = float(config.hard_exit_min_tvl_usd)
        if cur > 500:
            patch["hard_exit_min_tvl_usd"] = 250.0
    return patch


def _wallet_tune_patches(report: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    cap = report.get("wallet_capacity") or {}
    inner = cap.get("capacity") or {}
    bal = cap.get("balance") or {}
    sol = float(bal.get("sol") or 0.0)
    reserve = float(settings.get("reserve_sol") or inner.get("reserved_sol") or 0.05)
    pos = float(settings.get("position_size_sol") or inner.get("position_size_sol") or 0.01)
    mx = int(inner.get("max_positions") or 0)

    if sol > 0 and (mx <= 0 or sol < reserve + pos):
        spendable = max(0.0, sol - 0.002)
        new_reserve = min(reserve, _nice_floor(spendable * 0.15, 0.001))
        new_pos = _nice_floor(min(pos, spendable - new_reserve), 0.001)
        if new_pos < 0.001:
            new_pos = 0.001
        recs.append(
            {
                "id": "wallet_resize_for_live",
                "kind": "wallet",
                "title": "Resize SOL slots for your balance",
                "detail": (
                    f"Wallet has {sol:.4f} SOL but reserve_sol={reserve:.4f} and "
                    f"position_size_sol={pos:.4f} leave max_positions={mx}. "
                    f"Proposed reserve={new_reserve:.4f}, position_size={new_pos:.4f} "
                    "(still fund more SOL for reliable fees)."
                ),
                "risk": "medium",
                "default_checked": True,
                "settings_patch": {
                    "reserve_sol": new_reserve,
                    "position_size_sol": new_pos,
                },
            }
        )
    if sol < 0.05:
        recs.append(
            {
                "id": "wallet_low_sol",
                "kind": "wallet",
                "title": "Fund wallet with more SOL",
                "detail": (
                    f"Balance {sol:.4f} SOL is thin for CLMM opens + priority fees. "
                    "Target ≥0.1 SOL operational buffer before arming live opens."
                ),
                "risk": "high",
                "default_checked": False,
                "settings_patch": {},
            }
        )
    return recs


def _trade_ready_bundle(config: ScannerConfig, report: dict[str, Any]) -> dict[str, Any]:
    """One-click profile when funnel is closed but scans are running."""

    cand = int(report.get("candidate_count") or 0)
    patch: dict[str, Any] = {
        "pool_sort_field": "liquidity",
        "sort_type": "desc",
        "pool_type": "concentrated",
        "pages": max(int(config.pages), 2),
        "write_rejections": True,
    }
    if float(config.min_apr) > 80:
        patch["min_apr"] = _nice_floor(float(config.min_apr) * 0.5, 25.0)
    if float(config.min_liquidity_usd) > 10_000:
        patch["min_liquidity_usd"] = 5_000.0
    elif float(config.min_liquidity_usd) > 2_000:
        patch["min_liquidity_usd"] = 1_000.0
    if float(config.hard_exit_min_tvl_usd) > 300:
        patch["hard_exit_min_tvl_usd"] = 150.0
    if float(config.min_volume_24h_usd) > 5_000:
        patch["min_volume_24h_usd"] = 2_000.0
    title = "Trade-ready bundle (CLMM + liquidity sort)"
    detail = (
        "Applies a coordinated tune: Raydium pages sorted by liquidity (avoids APR-scam dust), "
        "keeps concentrated CLMM only, enables rejection CSV, and relaxes gates one step. "
        "Re-run scan after apply."
    )
    if cand > 0:
        title = "Refine funnel (liquidity sort + logging)"
        detail = (
            f"{cand} candidate(s) already pass — bundle still improves sort order and "
            "reject logging for the next cycle."
        )
    return {
        "id": "trade_ready_bundle",
        "kind": "bundle",
        "title": title,
        "detail": detail,
        "risk": "medium",
        "default_checked": cand == 0,
        "settings_patch": patch,
    }


def _live_readiness(settings: dict[str, Any]) -> dict[str, Any]:
    from raydium_lp1.doctor_advisor import _wallet_runtime
    from raydium_lp1.raydium_clmm import status as clmm_status
    from raydium_lp1.scanner import load_dotenv as _load_dotenv

    _load_dotenv()
    mode = mode_toggle.get_mode()
    wallet = _wallet_runtime()
    clmm = clmm_status()
    env_kp = (__import__("os").environ.get("SOLANA_KEYPAIR_PATH") or "").strip()
    kp_resolved = str(Path(env_kp).expanduser()) if env_kp else ""
    blockers: list[str] = []
    if mode != "live":
        blockers.append("mode is not live — toggle LIVE on dashboard")
    if not wallet.get("configured"):
        blockers.append("wallet address not configured")
    if mode == "live" and not wallet.get("has_private_key"):
        blockers.append("LIVE requires WALLET_PRIVATE_KEY or SOLANA_KEYPAIR_PATH in .env")
    if clmm.get("keypair_path_set") and not clmm.get("keypair_file_exists"):
        blockers.append(
            f"SOLANA_KEYPAIR_PATH is set but file missing: {kp_resolved or env_kp} "
            "(run .\\scripts\\import_wallet.ps1 -KeypairPath C:\\path\\to\\id.json)"
        )
    if not clmm.get("node_modules_present") or not clmm.get("node_binary"):
        blockers.append("CLMM Node bridge not installed (nodejs + npm install in raydium_clmm_node)")
    rpcs = settings.get("solana_rpc_urls") or []
    if not rpcs:
        blockers.append("no solana_rpc_urls in settings")
    try:
        from raydium_lp1.fee_guard import fee_guard_readiness_blockers

        blockers.extend(fee_guard_readiness_blockers(settings))
    except Exception:
        pass
    return {
        "mode": mode,
        "dry_run": bool(settings.get("dry_run", mode == "demo")),
        "wallet": wallet,
        "clmm": clmm,
        "keypair_path": env_kp,
        "keypair_path_set": bool(env_kp),
        "keypair_path_resolved": kp_resolved,
        "keypair_file_exists": bool(kp_resolved and Path(kp_resolved).is_file()),
        "ready_to_sign": len(blockers) == 0,
        "blockers": blockers,
    }


def build_tune_plan(
    *,
    latest_path: Path = DEFAULT_LATEST,
    settings_path: Path = DEFAULT_SETTINGS,
) -> dict[str, Any]:
    settings = load_settings_json(settings_path)
    report = _read_json(latest_path) or {}
    load_dotenv()
    try:
        config = ScannerConfig.from_file(settings_path)
    except ValueError as exc:
        return {"error": str(exc), "generated_at": _now_iso()}

    diagnosis = report.get("scan_diagnosis")
    if not isinstance(diagnosis, dict) or not diagnosis.get("setting_pressure"):
        diagnosis = build_scan_diagnosis(config, report)

    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    bundle = _trade_ready_bundle(config, report)
    items.append(bundle)

    for p in _wallet_tune_patches(report, settings):
        items.append(p)

    for idx, pressure in enumerate(diagnosis.get("setting_pressure") or []):
        if not isinstance(pressure, dict):
            continue
        sk = str(pressure.get("setting_key") or f"p{idx}")
        if sk in seen_keys and sk != "pool_sort_field":
            continue
        patch = _pressure_to_patch(pressure, config)
        if not patch:
            continue
        seen_keys.add(sk)
        items.append(
            {
                "id": f"tune_{sk}",
                "kind": "filter_tune",
                "title": f"Tune {sk}",
                "detail": pressure.get("concrete_suggestion") or pressure.get("rationale", ""),
                "risk": pressure.get("risk_if_changed", "medium"),
                "default_checked": float(pressure.get("reject_share_pct") or 0) >= 15.0,
                "settings_patch": patch,
                "reject_share_pct": pressure.get("reject_share_pct"),
                "direction": pressure.get("direction"),
            }
        )

    cand = int(report.get("candidate_count") or 0)
    if cand == 0:
        items.insert(
            0,
            {
                "id": "zero_candidates_note",
                "kind": "info",
                "title": "0 candidates — apply bundle then re-scan",
                "detail": (
                    "Your log shows many HARD rejects at $0 TVL (APR scam rows). "
                    "Sorting by liquidity + CLMM verification is required before live opens."
                ),
                "risk": "info",
                "default_checked": False,
                "settings_patch": {},
            },
        )

    scan_job: dict[str, Any] = {"running": False}
    try:
        from raydium_lp1.dashboard_scan_runner import scan_status

        scan_job = scan_status()
    except Exception:
        pass

    return {
        "generated_at": _now_iso(),
        "objective": dial_in_analyst.OBJECTIVE_BIAS_SUMMARY,
        "scan_summary": diagnosis.get("scan_summary") or {
            "scanned": report.get("scanned_count"),
            "candidates": report.get("candidate_count"),
            "rejected": report.get("rejected_count"),
        },
        "scan_status": scan_job,
        "live_readiness": _live_readiness(settings),
        "items": items[:16],
    }


def apply_tune_items(
    settings_path: Path,
    item_ids: list[str],
    *,
    latest_path: Path = DEFAULT_LATEST,
) -> dict[str, Any]:
    plan = build_tune_plan(latest_path=latest_path, settings_path=settings_path)
    by_id = {str(it["id"]): it for it in plan.get("items") or [] if isinstance(it, dict)}
    merged: dict[str, Any] = {}
    applied: list[str] = []
    for iid in item_ids:
        row = by_id.get(iid)
        if not row:
            continue
        patch = row.get("settings_patch") or {}
        if not isinstance(patch, dict) or not patch:
            applied.append(iid)
            continue
        merged.update(patch)
        applied.append(iid)
    if not merged:
        return {"ok": True, "applied_ids": applied, "merged_patch": {}, "message": "no settings keys in selection"}
    out = merge_known_settings_patch(settings_path, merged)
    return {"ok": True, "applied_ids": applied, "merged_patch": merged, "settings": out}
