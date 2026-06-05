"""Refresh dashboard JSON on read: live RPC wallet, dry-run paper wallet, paper LP state."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from raydium_lp1.dashboard import (
    _build_live_wallet_capacity,
    _candidate_to_simulated_trade,
)
from raydium_lp1.doctor_advisor import _wallet_runtime
from raydium_lp1.lp_fee_estimate import attach_fees_to_position, sum_open_fees_usd
from raydium_lp1.lp_order_strategies import STRATEGY_AUTO, build_open_order, catalog_dict
from raydium_lp1.scanner import ScannerConfig, assess_capacity, check_rpc_urls
from raydium_lp1 import wallet as wallet_mod

DEMO_STATE_PATH = Path("reports/demo_positions.json")
DEMO_PAPER_SOL_DEFAULT = 10.0
DEMO_WALLET_LABEL = "DRY_RUN-PAPER-WALLET"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _wallet_dict_for_ui(wallet: dict[str, Any] | None, runtime: dict[str, Any]) -> dict[str, Any]:
    if wallet and wallet.get("address"):
        return {**wallet, "configured": True, "address": str(wallet["address"])}
    if runtime.get("configured") and runtime.get("address"):
        return {
            "configured": True,
            "address": str(runtime["address"]),
            "source": str(runtime.get("source") or "runtime"),
            "has_private_key": bool(runtime.get("has_private_key")),
        }
    return {"configured": False}


def _attach_wallet(cap: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    out = dict(cap or {})
    w = out.get("wallet")
    out["wallet"] = _wallet_dict_for_ui(w if isinstance(w, dict) else None, runtime)
    return out


def _load_demo_state() -> dict[str, Any]:
    if not DEMO_STATE_PATH.is_file():
        return {"open": [], "closed": [], "updated_at": None}
    try:
        raw = json.loads(DEMO_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"open": [], "closed": [], "updated_at": None}
    if not isinstance(raw, dict):
        return {"open": [], "closed": [], "updated_at": None}
    return {
        "open": [dict(x) for x in (raw.get("open") or []) if isinstance(x, dict)],
        "closed": [dict(x) for x in (raw.get("closed") or []) if isinstance(x, dict)],
        "updated_at": raw.get("updated_at"),
    }


def _save_demo_state(state: dict[str, Any]) -> None:
    DEMO_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now_iso()
    DEMO_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _lp_settings(settings: dict[str, Any]) -> dict[str, float | str | bool]:
    return {
        "position_size_sol": float(settings.get("position_size_sol") or 0.01),
        "fee_bps": float(settings.get("lp_fee_bps") or 25.0),
        "strategy_id": str(settings.get("lp_active_strategy") or STRATEGY_AUTO),
        "default_width_pct": float(settings.get("lp_default_range_width_pct") or 20.0),
        "skew_momentum": bool(settings.get("lp_skew_use_momentum", True)),
    }


def _refresh_open_fees(
    rows: list[dict[str, Any]],
    cand_by_id: dict[str, dict[str, Any]],
    lp: dict[str, float | str | bool],
) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        pid = str(row.get("pool_id") or "")
        pool = cand_by_id.get(pid, row)
        out.append(
            attach_fees_to_position(
                row,
                pool,
                position_size_sol=float(lp["position_size_sol"]),
                fee_bps=float(lp["fee_bps"]),
            )
        )
    return out


def advance_demo_simulation(
    candidates: list[dict[str, Any]],
    *,
    settings: dict[str, Any],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Update paper LP opens/closes from latest scan candidates; return open, closed, combined feed."""

    lp = _lp_settings(settings)
    state = _load_demo_state()
    open_rows = {str(p.get("pool_id") or ""): dict(p) for p in state.get("open") or [] if p.get("pool_id")}
    closed_rows: list[dict] = list(state.get("closed") or [])

    current_ids: set[str] = set()
    cand_by_id: dict[str, dict] = {}
    for c in candidates:
        if not isinstance(c, dict):
            continue
        pid = str(c.get("id") or c.get("pool_id") or "")
        if not pid:
            continue
        current_ids.add(pid)
        cand_by_id[pid] = c

    for pid, pos in list(open_rows.items()):
        if pid not in current_ids:
            closed = {
                **pos,
                "action": "sim_close_lp",
                "status": "demo_closed",
                "closed_at": _now_iso(),
                "close_reason": "dropped_from_scan_shortlist",
            }
            closed_rows.append(closed)
            del open_rows[pid]

    for i, c in enumerate(candidates):
        if not isinstance(c, dict):
            continue
        pid = str(c.get("id") or "")
        if not pid or pid in open_rows:
            continue
        trade = _candidate_to_simulated_trade(c, len(open_rows) + 1)
        trade["opened_at"] = _now_iso()
        trade["status"] = "demo_open"
        trade["action"] = "sim_open_lp"
        mom = c.get("momentum") if isinstance(c.get("momentum"), dict) else {}
        order = build_open_order(
            c,
            mom,
            strategy_id=str(lp["strategy_id"]),
            default_width_pct=float(lp["default_width_pct"]),
            skew_use_momentum=bool(lp["skew_momentum"]),
        )
        trade["lp_order"] = order
        trade["strategy_id"] = order.get("strategy_id")
        trade["strategy_name"] = order.get("strategy_name")
        trade["width_pct"] = order.get("width_pct")
        open_rows[pid] = trade

    open_list = _refresh_open_fees(list(open_rows.values()), cand_by_id, lp)
    closed_rows = closed_rows[-80:]
    _save_demo_state({"open": open_list, "closed": closed_rows})

    feed: list[dict] = []
    for row in open_list:
        feed.append(row)
    for row in reversed(closed_rows[-20:]):
        feed.append(row)
    if not feed and candidates:
        feed = [
            _candidate_to_simulated_trade(c, i + 1)
            for i, c in enumerate(candidates)
            if isinstance(c, dict)
        ]
    return open_list, closed_rows, feed


def _build_demo_paper_wallet(
    report: dict[str, Any],
    settings: dict[str, Any],
    live_cap: dict[str, Any],
    *,
    open_positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    paper_sol = float(settings.get("demo_paper_sol") or DEMO_PAPER_SOL_DEFAULT)
    live_cap_inner = dict(live_cap.get("capacity") or {})
    pos_size = float(
        settings.get("position_size_sol") or live_cap_inner.get("position_size_sol") or 0.1
    )
    reserve = float(settings.get("reserve_sol") or live_cap_inner.get("reserved_sol") or 0.05)
    capacity = wallet_mod.compute_capacity(paper_sol, position_size_sol=pos_size, reserve_sol=reserve)
    cap_d = capacity.to_dict()
    n_cand = len(report.get("candidates") or [])
    cap_d["simulated_slots"] = n_cand
    cap_d["max_positions"] = capacity.max_positions
    cap_d["fees_collected_usd"] = sum_open_fees_usd(open_positions or [])
    cap_d["note"] = (
        "Dry-run paper wallet — balances are paper only. LP open/close follows real scan candidates "
        f"(state in {DEMO_STATE_PATH.as_posix()})."
    )
    return {
        "wallet": {
            "configured": True,
            "address": DEMO_WALLET_LABEL,
            "source": "demo_sim",
            "simulated": True,
            "has_private_key": False,
        },
        "balance": {
            "ok": True,
            "sol": paper_sol,
            "lamports": int(paper_sol * wallet_mod.LAMPORTS_PER_SOL),
            "paper": True,
        },
        "capacity": cap_d,
        "simulated": True,
    }


def fresh_live_wallet_capacity(settings_path: Path) -> dict[str, Any]:
    from raydium_lp1.scanner import load_dotenv

    load_dotenv()
    runtime = _wallet_runtime()
    config = ScannerConfig.from_file(settings_path)
    wallet_config = wallet_mod.load_wallet()
    if wallet_config is None and runtime.get("configured") and runtime.get("address"):
        wallet_config = wallet_mod.WalletConfig(
            address=str(runtime["address"]),
            private_key="",
            source=str(runtime.get("source") or "settings"),
        )
    cap = assess_capacity(config, wallet_config)
    return _attach_wallet(cap, runtime)


def enrich_dashboard_payload(data: dict[str, Any], settings_path: Path) -> dict[str, Any]:
    """Merge live RPC wallet + demo simulation into a dashboard.json-shaped dict."""

    out = copy.deepcopy(data)
    settings = dict(out.get("settings") or {})
    try:
        from raydium_lp1.settings_io import load_settings_json

        settings = {**load_settings_json(settings_path), **settings}
    except (OSError, ValueError):
        pass

    live_cap = fresh_live_wallet_capacity(settings_path)
    out["wallet_capacity"] = live_cap
    out["live_wallet_capacity"] = _attach_wallet(_build_live_wallet_capacity(live_cap), _wallet_runtime())

    last_scan = dict(out.get("last_scan") or {})
    candidates = list(last_scan.get("candidates") or [])
    report_stub = {
        "candidates": candidates,
        "candidate_count_pre_capacity": last_scan.get("candidate_count_pre_capacity"),
        "candidate_count": last_scan.get("candidate_count"),
    }

    lp = _lp_settings(settings)
    cand_by_id = {
        str(c.get("id") or ""): c for c in candidates if isinstance(c, dict) and c.get("id")
    }
    demo_open, demo_closed, demo_feed = advance_demo_simulation(candidates, settings=settings)
    out["demo_open_positions"] = demo_open
    out["demo_closed_positions"] = demo_closed
    out["demo_simulated_trades"] = demo_feed
    out["demo_wallet_capacity"] = _build_demo_paper_wallet(
        report_stub, settings, live_cap, open_positions=demo_open
    )

    from raydium_lp1.dashboard import _load_live_positions_file

    repo_root = settings_path.resolve().parent.parent
    disk_live = _load_live_positions_file(repo_root / "active_positions.json")
    merged_live: list[dict[str, Any]] = []
    seen_nft: set[str] = set()
    for row in list(out.get("live_open_positions") or []) + disk_live:
        if not isinstance(row, dict):
            continue
        key = str(row.get("position_nft_mint") or row.get("pool_id") or "")
        if key and key in seen_nft:
            continue
        if key:
            seen_nft.add(key)
        merged_live.append(row)
    live_open = _refresh_open_fees(merged_live, cand_by_id, lp)
    try:
        from raydium_lp1.lp_open_style import annotate_live_positions
        from raydium_lp1.lp_style_performance import build_live_style_report
        from raydium_lp1.scanner import ScannerConfig

        cfg = ScannerConfig.from_file(settings_path)
        live_open = annotate_live_positions(live_open, cfg)
        out["live_lp_style_report"] = build_live_style_report(live_open)
    except Exception as exc:
        out["live_lp_style_report"] = {"error": str(exc)}
    for row in live_open:
        row.setdefault("status", row.get("status") or "live_open")
        row.setdefault("simulated", False)
        if row.get("position_nft_mint") and not row.get("action"):
            row["action"] = "live_clmm"
    sol_px_econ = 180.0
    try:
        from raydium_lp1.fee_guard import fee_config_from_settings
        from raydium_lp1.scanner import ScannerConfig

        cfg_e = ScannerConfig.from_file(settings_path)
        sol_px_econ = float(fee_config_from_settings(cfg_e).sol_price_usd or 180.0)
    except Exception:
        pass
    try:
        from raydium_lp1.lp_position_economics import OPEN_ECONOMICS_TIPS, enrich_positions

        live_open = enrich_positions(live_open, sol_price_usd=sol_px_econ)
        demo_open = enrich_positions(list(out.get("demo_open_positions") or []), sol_price_usd=sol_px_econ)
        out["demo_open_positions"] = demo_open
        demo_trades = enrich_positions(list(out.get("demo_simulated_trades") or []), sol_price_usd=sol_px_econ)
        out["demo_simulated_trades"] = demo_trades
        out["open_economics_tips"] = list(OPEN_ECONOMICS_TIPS)
    except Exception as exc:
        out["open_economics_tips"] = []
        out["open_economics_enrich_error"] = str(exc)
    out["live_open_positions"] = live_open
    out["active_positions_count"] = len(live_open)
    live_wc = dict(out["live_wallet_capacity"])
    live_cap_inner = dict(live_wc.get("capacity") or {})
    live_cap_inner["fees_collected_usd"] = sum_open_fees_usd(live_open)
    live_wc["capacity"] = live_cap_inner
    out["live_wallet_capacity"] = live_wc
    out["lp_strategy_catalog"] = catalog_dict()
    try:
        from raydium_lp1.lp_selection import selection_summary
        from raydium_lp1.scanner import ScannerConfig

        cfg = ScannerConfig.from_file(settings_path)
        out["lp_selection"] = selection_summary(cfg, {"candidates": candidates})
    except Exception as exc:
        out["lp_selection"] = {"error": str(exc)}

    if not out.get("rpc_health"):
        try:
            config = ScannerConfig.from_file(settings_path)
            out["rpc_health"] = check_rpc_urls(list(config.solana_rpc_urls))
        except Exception:
            pass

    try:
        from raydium_lp1 import emergency
        from raydium_lp1.settings_io import load_settings_json

        alerts_path = Path(
            str(load_settings_json(settings_path).get("emergency_alerts_path", "reports/alerts.json"))
        )
        out["emergency_banner"] = emergency.latest_emergency_close_banner(alerts_path)
    except Exception:
        out["emergency_banner"] = None

    out["feed_refreshed_at"] = _now_iso()
    return out
