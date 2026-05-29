"""How LIVE picks which pool to open: APR-first vs momentum HOT-first."""

from __future__ import annotations

from typing import Any

LP_SELECTION_APR = "apr"
LP_SELECTION_MOMENTUM = "momentum"
VALID_LP_SELECTION = frozenset({LP_SELECTION_APR, LP_SELECTION_MOMENTUM})


def normalize_lp_selection_mode(raw: str | None) -> str:
    m = (raw or LP_SELECTION_APR).strip().lower()
    if m in ("mom", "momentum", "hot", "mom_hot"):
        return LP_SELECTION_MOMENTUM
    if m in ("apr", "apy", "yield"):
        return LP_SELECTION_APR
    return m if m in VALID_LP_SELECTION else LP_SELECTION_APR


def _mom_score(pool: dict[str, Any]) -> float:
    mom = pool.get("momentum") if isinstance(pool.get("momentum"), dict) else {}
    try:
        return float(mom.get("combined_score") or mom.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _mom_tier(pool: dict[str, Any]) -> str:
    mom = pool.get("momentum") if isinstance(pool.get("momentum"), dict) else {}
    return str(mom.get("tier") or pool.get("momentum_tier") or "").lower()


def is_momentum_hot(pool: dict[str, Any]) -> bool:
    """Strict HOT tier for MoM live picks (matches dashboard green-row intent)."""
    return _mom_tier(pool) == "hot"


def sort_candidates_for_display(candidates: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    mode = normalize_lp_selection_mode(mode)
    rows = [dict(p) for p in candidates if isinstance(p, dict)]
    if mode == LP_SELECTION_MOMENTUM:
        return sorted(rows, key=_mom_score, reverse=True)
    return sorted(rows, key=lambda p: float(p.get("apr") or 0), reverse=True)


def apply_candidate_order(candidates: list[dict[str, Any]], config: Any) -> list[dict[str, Any]]:
    """Reorder scanner shortlist so index 0 matches the active LP selection mode."""
    mode = normalize_lp_selection_mode(getattr(config, "lp_selection_mode", LP_SELECTION_APR))
    if mode == LP_SELECTION_MOMENTUM:
        if getattr(config, "sort_candidates_by_momentum", True):
            return sort_candidates_for_display(candidates, LP_SELECTION_MOMENTUM)
        return candidates
    return sort_candidates_for_display(candidates, LP_SELECTION_APR)


def fetch_pool_by_id(pool_id: str, *, config: Any) -> dict[str, Any]:
    """Load one pool from Raydium ``/pools/info/ids`` when it is not in the scan shortlist."""

    from raydium_lp1 import pool_verify
    from raydium_lp1.scanner import normalize_pool

    pid = str(pool_id).strip()
    if not pid:
        raise ValueError("pool_id is empty")
    raw = pool_verify.fetch_raydium_pool_by_id(
        pid,
        api_base=str(getattr(config, "raydium_api_base", "https://api-v3.raydium.io")),
        timeout=max(3, int(getattr(config, "http_timeout_seconds", 15) or 15)),
    )
    if not raw:
        raise ValueError(
            f"pool_id {pid!r} not found on Raydium API "
            f"({pool_verify.raydium_verify_url(str(getattr(config, 'raydium_api_base', '')), pid)})"
        )
    pool = normalize_pool(raw, str(getattr(config, "apr_field", "apr24h")))
    if getattr(config, "require_verified_raydium_pool", True):
        pv = pool_verify.validate_pool(
            pool,
            api_base=str(getattr(config, "raydium_api_base", "https://api-v3.raydium.io")),
            rpc_urls=list(getattr(config, "solana_rpc_urls", []) or []),
            verify_on_chain=bool(getattr(config, "verify_pool_on_chain", True)),
            verify_raydium_api=bool(getattr(config, "verify_pool_raydium_api", False)),
        )
        pool["pool_verification"] = pv.to_dict() if hasattr(pv, "to_dict") else {
            "ok": pv.ok,
            "reasons": list(pv.reasons),
            "proof_tag": pv.proof_tag,
        }
    pool["fetched_for_live_open"] = True
    return pool


def pick_live_candidate(
    report: dict[str, Any],
    pool_id: str | None,
    *,
    config: Any | None = None,
    fetch_if_missing: bool = True,
) -> dict[str, Any]:
    """Choose pool for ``open_clmm_candidate`` (explicit id or mode-based top)."""

    pools = [p for p in (report.get("candidates") or []) if isinstance(p, dict)]
    if pool_id:
        pid = str(pool_id).strip()
        for p in pools:
            if str(p.get("id") or "") == pid:
                return p
        if fetch_if_missing and config is not None:
            return fetch_pool_by_id(pid, config=config)
        raise ValueError(
            f"pool_id {pid!r} not in latest candidates — re-scan after tune "
            "or pass fetch_if_missing=True"
        )

    if not pools:
        raise ValueError("no candidates in latest.json — run scan with tuned settings first")

    mode = LP_SELECTION_APR
    if config is not None:
        mode = normalize_lp_selection_mode(getattr(config, "lp_selection_mode", LP_SELECTION_APR))

    if mode == LP_SELECTION_MOMENTUM:
        hot = [p for p in pools if is_momentum_hot(p)]
        if not hot:
            tiers = sorted({_mom_tier(p) or "?" for p in pools})
            raise ValueError(
                "MoM pick mode: no candidate with momentum tier HOT. "
                f"Tiers in shortlist: {', '.join(tiers)}. "
                "Wait for HOT or switch LP pick to APR."
            )
        return sort_candidates_for_display(hot, LP_SELECTION_MOMENTUM)[0]

    return sort_candidates_for_display(pools, LP_SELECTION_APR)[0]


def selection_summary(config: Any, report: dict[str, Any] | None = None) -> dict[str, Any]:
    mode = normalize_lp_selection_mode(getattr(config, "lp_selection_mode", LP_SELECTION_APR))
    out: dict[str, Any] = {
        "lp_selection_mode": mode,
        "label": "MoM HOT" if mode == LP_SELECTION_MOMENTUM else "APR",
        "live_picks": "top momentum tier=hot by combined score"
        if mode == LP_SELECTION_MOMENTUM
        else "top candidate by APR %",
    }
    if report:
        try:
            top = pick_live_candidate(report, None, config=config)
            out["top_pool_id"] = top.get("id")
            out["top_pair"] = f"{top.get('mint_a_symbol')}/{top.get('mint_b_symbol')}"
            out["top_apr"] = top.get("apr")
            mom = top.get("momentum") if isinstance(top.get("momentum"), dict) else {}
            out["top_momentum_tier"] = mom.get("tier")
            out["top_momentum_score"] = mom.get("combined_score") or mom.get("score")
        except ValueError as exc:
            out["top_pick_error"] = str(exc)
    return out
