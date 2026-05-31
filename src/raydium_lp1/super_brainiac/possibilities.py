"""SUPER-BRAINIAC_POSSIBILITIES — scan, score, and optional LIVE open for fee-capture experiments."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from raydium_lp1 import lp_order_strategies, lp_range_planner, routes
from raydium_lp1.lp_order_strategies import ALL_STRATEGY_IDS, build_open_order
from raydium_lp1.lp_pay_mint import allowed_pay_symbols, resolve_pay_mint
from raydium_lp1.scanner import (
    RAYDIUM_CLMM_PROGRAM_ID,
    ScannerConfig,
    extract_pool_items,
    fetch_json_with_retries,
    normalize_pool,
    pool_list_url,
)
from raydium_lp1.super_brainiac.create_pool_analysis import analyze_create_pool_feasibility

REPO = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH = REPO / "reports" / "super_brainiac_latest.json"

# Plain-language logic blocks for dashboard (editable via settings keys below).
LOGIC_DOCS: dict[str, Any] = {
    "module": "SUPER-BRAINIAC_POSSIBILITIES",
    "purpose": (
        "Continuously scan Raydium CLMM pools, keep only pools with enough depth and "
        "two-way routes, then score every LP order style to estimate which configuration "
        "maximizes your share of observed 24h fees for a small deposit."
    ),
    "universe_filters": [
        "Concentrated CLMM program id only.",
        "Pool TVL >= super_brainiac_min_liquidity_usd (default $5,000).",
        "Pair shape PAY/ALT only — one SOL/USDC/USDT leg + one non-pay token (no SOL/USDC, SOL/USDT, etc.).",
        "Both mints must sell to SOL/USDC/USDT (exit routes).",
        "Non-stable mint must be buyable from SOL/USDC/USDT (entry routes for funding).",
        "Optional: prefer newer pools (open_time within max age window).",
    ],
    "pair_shape_rule": (
        "Detective scans reject double-pay pools (two quote legs). We only score PAY + newish/memecoin "
        "alt pairs so pay-token-only opens match how you LP."
    ),
    "scoring_model": [
        "observed_pool_fee_24h_usd from Raydium day.volumeFee.",
        "your_share ≈ (deposit_usd / pool_TVL) × fee_24h × in_range_factor × width_efficiency.",
        "theoretical_apr_pct = (your_est_fee_usd / deposit_usd) × 365 × 100.",
        "in_range_factor: overlap of 24h priceMin–priceMax with strategy band vs spot.",
        "width_efficiency: tighter bands earn more per dollar when in-range (capped).",
        "fee_tier_boost: favors 1%–4% pool feeRate; still picks 0.115%+ if expected $ wins.",
    ],
    "strategy_pick": (
        "For each pool we simulate centered_tight, asymmetric, ATR width, trailing skew, "
        "full range, and auto. Highest brainiac_score wins; that strategy_id is used on LIVE open."
    ),
    "apr_target_note": (
        "Display threshold super_brainiac_target_apr_pct (default 999.99) is a experiment label — "
        "real chains rarely sustain that APR; we rank by expected fee USD and confidence, not headline APR."
    ),
    "auto_open": (
        "When super_brainiac_auto_open_live is true, run-once picks the top passing pool and "
        "opens with super_brainiac_deposit_usd using normal pay-token, fee-guard, and manual-live rules."
    ),
    "spend_less_get_more": (
        "SPEND LESS=GET MORE runs on every detective scan and LIVE open: estimates sunk rent vs deposit, "
        "wallet headroom, clamps deposit when auto_clamp is on, and can fall back from wide band to "
        "single-sided on SOL/alt when micro deposits fail the rent cap."
    ),
}


@dataclass
class BrainiacConfig:
    enabled: bool = True
    min_liquidity_usd: float = 5000.0
    deposit_usd: float = 3.0
    target_apr_pct: float = 999.99
    auto_open_live: bool = False
    scan_pages: int = 8
    page_size: int = 100
    pool_sort_field: str = "volume24h"
    sort_type: str = "desc"
    prefer_new_pools: bool = True
    max_pool_age_hours: float = 168.0
    min_pool_age_hours: float = 0.05
    prefer_fee_pct_min: float = 1.0
    prefer_fee_pct_max: float = 4.0
    require_buy_route: bool = True
    require_sell_route: bool = True
    max_route_price_impact_pct: float = 5.0
    min_score_to_open: float = 0.0001
    min_confidence: float = 0.35
    report_path: str = "reports/super_brainiac_latest.json"
    continuous_interval_sec: float = 90.0
    require_pay_alt_pair_only: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, scanner: ScannerConfig | None = None) -> BrainiacConfig:
        def _f(key: str, default: float) -> float:
            v = raw.get(key, default)
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        def _b(key: str, default: bool) -> bool:
            return bool(raw.get(key, default))

        def _i(key: str, default: int) -> int:
            try:
                return int(raw.get(key, default))
            except (TypeError, ValueError):
                return default

        bases = tuple(
            s.upper()
            for s in (raw.get("allowed_quote_symbols") or getattr(scanner, "allowed_quote_symbols", ("SOL", "USDC", "USDT")))
        )
        _ = bases  # used by callers via scanner config
        return cls(
            enabled=_b("super_brainiac_enabled", True),
            min_liquidity_usd=_f("super_brainiac_min_liquidity_usd", 5000.0),
            deposit_usd=_f("super_brainiac_deposit_usd", 3.0),
            target_apr_pct=_f("super_brainiac_target_apr_pct", 999.99),
            auto_open_live=_b("super_brainiac_auto_open_live", False),
            scan_pages=max(1, min(50, _i("super_brainiac_scan_pages", 8))),
            page_size=max(10, min(1000, _i("super_brainiac_page_size", 100))),
            pool_sort_field=str(raw.get("super_brainiac_pool_sort_field") or "volume24h"),
            sort_type=str(raw.get("super_brainiac_sort_type") or "desc"),
            prefer_new_pools=_b("super_brainiac_prefer_new_pools", True),
            max_pool_age_hours=_f("super_brainiac_max_pool_age_hours", 168.0),
            min_pool_age_hours=_f("super_brainiac_min_pool_age_hours", 0.05),
            prefer_fee_pct_min=_f("super_brainiac_prefer_fee_pct_min", 1.0),
            prefer_fee_pct_max=_f("super_brainiac_prefer_fee_pct_max", 4.0),
            require_buy_route=_b("super_brainiac_require_buy_route", True),
            require_sell_route=_b("super_brainiac_require_sell_route", True),
            max_route_price_impact_pct=_f(
                "super_brainiac_max_route_price_impact_pct",
                float(raw.get("max_route_price_impact_pct", 5.0) or 5.0),
            ),
            min_score_to_open=_f("super_brainiac_min_score_to_open", 0.0001),
            min_confidence=_f("super_brainiac_min_confidence", 0.35),
            report_path=str(raw.get("super_brainiac_report_path") or "reports/super_brainiac_latest.json"),
            continuous_interval_sec=_f("super_brainiac_continuous_interval_sec", 90.0),
            require_pay_alt_pair_only=_b("super_brainiac_require_pay_alt_pair_only", True),
        )


def _norm_symbol(sym: str) -> str:
    s = (sym or "").strip().upper()
    return "SOL" if s == "WSOL" else s


def classify_pay_alt_pair(
    pool: Mapping[str, Any],
    *,
    allowed_pay: frozenset[str] | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    """Detective pair shape: exactly one pay leg + one alt (not SOL/USDC style)."""

    pay_set = allowed_pay or allowed_pay_symbols(config)
    a = _norm_symbol(str(pool.get("mint_a_symbol") or ""))
    b = _norm_symbol(str(pool.get("mint_b_symbol") or ""))
    a_pay = a in pay_set
    b_pay = b in pay_set
    if a_pay and b_pay:
        return {
            "ok": False,
            "pair_shape": "pay/pay",
            "reason": f"double-pay pair {a}/{b} (detective wants PAY/ALT only)",
        }
    if not a_pay and not b_pay:
        return {
            "ok": False,
            "pair_shape": "alt/alt",
            "reason": f"no pay leg on {a}/{b}",
        }
    pay_sym = a if a_pay else b
    alt_sym = b if a_pay else a
    return {
        "ok": True,
        "pair_shape": "pay/alt",
        "pay_symbol": pay_sym,
        "alt_symbol": alt_sym,
        "pair_label": f"{pay_sym}/{alt_sym}",
    }


def load_brainiac_config(settings_path: Path | None = None) -> tuple[BrainiacConfig, ScannerConfig]:
    path = settings_path or (REPO / "config" / "settings.json")
    scanner = ScannerConfig.from_file(path)
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return BrainiacConfig.from_mapping(raw, scanner=scanner), scanner


def report_path(cfg: BrainiacConfig) -> Path:
    p = Path(cfg.report_path)
    return p if p.is_absolute() else REPO / p


def fee_rate_as_percent(pool: Mapping[str, Any]) -> float:
    fr = float(pool.get("fee_rate") or 0)
    if fr <= 0:
        return 0.0
    if fr < 0.2:
        return fr * 100.0
    return fr


def fee_tier_boost(fee_pct: float, cfg: BrainiacConfig) -> float:
    if cfg.prefer_fee_pct_min <= fee_pct <= cfg.prefer_fee_pct_max:
        return 1.4
    if fee_pct >= 0.115:
        return 1.0 + min(0.35, fee_pct / max(cfg.prefer_fee_pct_max, 0.01))
    return 0.85


def pool_age_hours(pool: Mapping[str, Any]) -> float | None:
    ts = int(pool.get("open_time") or 0)
    if ts <= 0:
        return None
    now = datetime.now(UTC).timestamp()
    return max(0.0, (now - ts) / 3600.0)


def _width_efficiency(width_pct: float, placement: str) -> float:
    w = max(4.0, float(width_pct))
    if placement in ("wide_band", "full_range"):
        return 0.35
    if placement in ("single_above", "single_below"):
        return min(2.2, 1.15 / (w / 100.0))
    return min(2.5, 1.35 / (w / 100.0))


def in_range_factor(
    pool: Mapping[str, Any],
    *,
    width_pct: float,
    placement: str,
    skew: float,
) -> float:
    spot, _ = lp_range_planner.spot_price_quote_per_base(pool)
    raw = pool.get("raw") if isinstance(pool.get("raw"), dict) else {}
    day = raw.get("day") if isinstance(raw.get("day"), dict) else {}
    pmin = float(day.get("priceMin") or 0)
    pmax = float(day.get("priceMax") or 0)

    if placement in ("wide_band", "full_range"):
        return 0.82

    if spot is None or pmin <= 0 or pmax <= pmin:
        return 0.42 if placement == "centered" else 0.28

    lo, hi = lp_range_planner.asymmetric_quote_band(spot, width_pct, skew)
    overlap = max(0.0, min(hi, pmax) - max(lo, pmin))
    span = pmax - pmin
    overlap_ratio = overlap / span if span > 0 else 0.0

    if placement in ("single_above", "single_below"):
        return max(0.12, min(0.72, overlap_ratio * 0.85 + 0.1))
    return max(0.22, min(0.94, overlap_ratio * 0.92 + 0.08))


def check_pool_buy_routes(
    pool: Mapping[str, Any],
    *,
    base_symbols: tuple[str, ...],
    sources: tuple[str, ...],
    max_route_price_impact_pct: float,
) -> tuple[bool, list[str]]:
    """Quote → alt mint routes (for funding the non-pay leg)."""

    reasons: list[str] = []
    stable = {"SOL", "USDC", "USDT", "USD1", "WSOL"}
    sym_a = str(pool.get("mint_a_symbol") or "").upper()
    sym_b = str(pool.get("mint_b_symbol") or "").upper()
    mint_a = str(pool.get("mint_a") or "")
    mint_b = str(pool.get("mint_b") or "")

    def _need_buy(sym: str, mint: str) -> bool:
        return sym not in stable and bool(mint)

    targets: list[tuple[str, str]] = []
    if _need_buy(sym_a, mint_a):
        targets.append((sym_a, mint_a))
    if _need_buy(sym_b, mint_b):
        targets.append((sym_b, mint_b))
    if not targets:
        return True, []

    from raydium_lp1.routes import BASE_TOKENS, check_jupiter_route

    ok_any = False
    for sym, mint in targets:
        leg_ok = False
        for base_sym in base_symbols:
            base_mint = BASE_TOKENS.get(base_sym.upper())
            if not base_mint:
                continue
            rec = check_jupiter_route(
                base_mint,
                mint,
                max_price_impact_pct=max_route_price_impact_pct or None,
            )
            if rec.get("ok"):
                leg_ok = True
                ok_any = True
                break
        if not leg_ok:
            reasons.append(f"no buy route {sym} from {','.join(base_symbols)}")
    return (not reasons, reasons)


def pool_passes_universe(
    pool: Mapping[str, Any],
    cfg: BrainiacConfig,
    scanner: ScannerConfig,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    pid = str(pool.get("program_id") or "")
    if pid and pid != RAYDIUM_CLMM_PROGRAM_ID:
        reasons.append("not CLMM")
    elif not pid and not lp_range_planner.is_clmm_style_pool(pool):
        reasons.append("not CLMM (type)")
    liq = float(pool.get("liquidity_usd") or 0)
    if liq < cfg.min_liquidity_usd:
        reasons.append(f"TVL ${liq:.0f} < ${cfg.min_liquidity_usd:.0f}")
    age = pool_age_hours(pool)
    if age is not None:
        if age < cfg.min_pool_age_hours:
            reasons.append(f"pool too new ({age:.2f}h)")
        elif cfg.prefer_new_pools and age > cfg.max_pool_age_hours:
            reasons.append(f"pool too old ({age:.0f}h > {cfg.max_pool_age_hours:.0f}h)")
    vol = float(pool.get("volume_24h_usd") or 0)
    if vol <= 0:
        reasons.append("zero 24h volume")

    if cfg.require_pay_alt_pair_only:
        shape = classify_pay_alt_pair(pool, config=scanner)
        if not shape.get("ok"):
            reasons.append(str(shape.get("reason") or "not PAY/ALT pair"))

    bases = tuple(s.upper() for s in sorted(scanner.allowed_quote_symbols))
    impact = cfg.max_route_price_impact_pct if cfg.max_route_price_impact_pct > 0 else 0.0
    if cfg.require_sell_route:
        sell = routes.check_pool_sellability(
            dict(pool),
            base_symbols=bases,
            sources=scanner.route_sources,
            max_route_price_impact_pct=impact,
        )
        if not sell.ok:
            reasons.extend(sell.reasons[:2])
    if cfg.require_buy_route:
        buy_ok, buy_reasons = check_pool_buy_routes(
            pool,
            base_symbols=bases,
            sources=scanner.route_sources,
            max_route_price_impact_pct=impact,
        )
        if not buy_ok:
            reasons.extend(buy_reasons[:2])
    pay = resolve_pay_mint(pool, scanner)
    if pay is None and scanner.lp_open_pay_token_only:
        reasons.append("no SOL/USDC/USDT pay leg")
    return (not reasons, reasons)


def score_strategy_for_pool(
    pool: Mapping[str, Any],
    strategy_id: str,
    *,
    cfg: BrainiacConfig,
    scanner: ScannerConfig,
) -> dict[str, Any]:
    mom = pool.get("momentum") if isinstance(pool.get("momentum"), dict) else None
    plan = build_open_order(
        pool,
        mom,
        strategy_id=strategy_id,
        default_width_pct=float(getattr(scanner, "lp_default_range_width_pct", 20.0) or 20.0),
        skew_use_momentum=bool(getattr(scanner, "lp_skew_use_momentum", True)),
    )
    sid = str(plan.get("strategy_id") or strategy_id)
    width = float(plan.get("width_pct") or 20.0)
    skew = float(plan.get("skew") or 0.0)

    placement = "centered"
    if sid == lp_order_strategies.STRATEGY_FULL_RANGE:
        placement = "wide_band"
    elif sid == lp_order_strategies.STRATEGY_ASYMMETRIC or (
        sid == lp_order_strategies.STRATEGY_TRAILING_SKEW and abs(skew) >= 0.08
    ):
        band = plan.get("band") if isinstance(plan.get("band"), dict) else {}
        ot = str(band.get("order_type") or ("bullish" if skew >= 0 else "bearish")).lower()
        placement = "single_above" if ot in ("bullish", "above", "sell") else "single_below"

    ir = in_range_factor(pool, width_pct=width, placement=placement, skew=skew)
    we = _width_efficiency(width, placement)
    tvl = max(1.0, float(pool.get("liquidity_usd") or 1.0))
    fee_24h = float(pool.get("fee_24h_usd") or 0)
    deposit = max(0.01, cfg.deposit_usd)
    churn = float(pool.get("volume_24h_usd") or 0) / tvl
    churn_boost = min(2.0, 1.0 + churn * 0.25)

    est_fee_usd = (deposit / tvl) * fee_24h * ir * we
    theoretical_apr = (est_fee_usd / deposit) * 365.0 * 100.0 if deposit > 0 else 0.0
    fee_pct = fee_rate_as_percent(pool)
    tier_boost = fee_tier_boost(fee_pct, cfg)
    score = est_fee_usd * tier_boost * churn_boost
    confidence = min(0.98, ir * we * min(1.0, churn / 2.0 + 0.35))

    return {
        "strategy_id": sid,
        "strategy_name": plan.get("strategy_name"),
        "placement": placement,
        "width_pct": width,
        "skew": skew,
        "in_range_factor": round(ir, 4),
        "width_efficiency": round(we, 4),
        "est_fee_usd_24h": round(est_fee_usd, 6),
        "theoretical_apr_pct": round(theoretical_apr, 2),
        "fee_tier_pct": round(fee_pct, 4),
        "tier_boost": round(tier_boost, 3),
        "churn_24h": round(churn, 4),
        "brainiac_score": round(score, 8),
        "confidence": round(confidence, 4),
        "meets_apr_target": theoretical_apr >= cfg.target_apr_pct,
    }


def score_pool(
    pool: Mapping[str, Any],
    *,
    cfg: BrainiacConfig,
    scanner: ScannerConfig,
) -> dict[str, Any] | None:
    ok, reasons = pool_passes_universe(pool, cfg, scanner)
    if not ok:
        return None
    strategies = [score_strategy_for_pool(pool, sid, cfg=cfg, scanner=scanner) for sid in ALL_STRATEGY_IDS]
    best = max(strategies, key=lambda s: float(s.get("brainiac_score") or 0))
    age = pool_age_hours(pool)
    shape = classify_pay_alt_pair(pool, config=scanner)
    return {
        "pool_id": pool.get("id"),
        "pair": f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "pair_shape": shape.get("pair_shape"),
        "pair_label": shape.get("pair_label") or f"{pool.get('mint_a_symbol')}/{pool.get('mint_b_symbol')}",
        "pay_symbol": shape.get("pay_symbol"),
        "alt_symbol": shape.get("alt_symbol"),
        "liquidity_usd": pool.get("liquidity_usd"),
        "volume_24h_usd": pool.get("volume_24h_usd"),
        "fee_24h_usd": pool.get("fee_24h_usd"),
        "apr_reported": pool.get("apr"),
        "fee_tier_pct": fee_rate_as_percent(pool),
        "pool_age_hours": round(age, 2) if age is not None else None,
        "best_strategy": best,
        "strategy_ranking": sorted(strategies, key=lambda s: -float(s.get("brainiac_score") or 0))[:4],
        "universe_ok": True,
        "reject_reasons": reasons,
    }


def scan_brainiac_universe(
    *,
    cfg: BrainiacConfig | None = None,
    scanner: ScannerConfig | None = None,
    settings_path: Path | None = None,
) -> dict[str, Any]:
    spath = settings_path or (REPO / "config" / "settings.json")
    if cfg is None or scanner is None:
        cfg, scanner = load_brainiac_config(spath)

    from dataclasses import replace

    scan_cfg = replace(
        scanner,
        pages=cfg.scan_pages,
        page_size=cfg.page_size,
        pool_sort_field=cfg.pool_sort_field,
        sort_type=cfg.sort_type,
        min_liquidity_usd=min(cfg.min_liquidity_usd, scanner.min_liquidity_usd),
    )

    t0 = time.time()
    pools_raw: list[dict[str, Any]] = []
    errors: list[str] = []
    for page in range(1, cfg.scan_pages + 1):
        url = pool_list_url(scan_cfg, page=page)
        try:
            resp = fetch_json_with_retries(url, timeout=scan_cfg.http_timeout_seconds)
            items = extract_pool_items(resp)
            pools_raw.extend(normalize_pool(it, scan_cfg.apr_field) for it in items)
        except RuntimeError as exc:
            errors.append(f"page {page}: {exc}")
            if not pools_raw:
                raise
            break
        if page < cfg.scan_pages and scan_cfg.page_delay_seconds > 0:
            time.sleep(scan_cfg.page_delay_seconds)

    def _cheap_ok(pool: dict[str, Any]) -> bool:
        if float(pool.get("liquidity_usd") or 0) < cfg.min_liquidity_usd:
            return False
        if float(pool.get("volume_24h_usd") or 0) <= 0:
            return False
        pid = str(pool.get("program_id") or "")
        if pid and pid != RAYDIUM_CLMM_PROGRAM_ID:
            return False
        if not pid and not lp_range_planner.is_clmm_style_pool(pool):
            return False
        age = pool_age_hours(pool)
        if age is not None and age < cfg.min_pool_age_hours:
            return False
        if cfg.prefer_new_pools and age is not None and age > cfg.max_pool_age_hours:
            return False
        if cfg.require_pay_alt_pair_only:
            shape = classify_pay_alt_pair(pool, config=scanner)
            if not shape.get("ok"):
                return False
        return True

    prefiltered = [p for p in pools_raw if _cheap_ok(p)]
    prefiltered.sort(
        key=lambda p: (
            -float(p.get("fee_24h_usd") or 0),
            -float(p.get("volume_24h_usd") or 0) / max(1.0, float(p.get("liquidity_usd") or 1)),
        ),
    )
    route_cap = max(20, min(80, cfg.scan_pages * 12))

    scored: list[dict[str, Any]] = []
    rejected = len(pools_raw) - len(prefiltered)
    for pool in prefiltered[:route_cap]:
        row = score_pool(pool, cfg=cfg, scanner=scanner)
        if row:
            scored.append(row)
        else:
            rejected += 1
    rejected += max(0, len(prefiltered) - route_cap)

    scored.sort(
        key=lambda r: (
            -float((r.get("best_strategy") or {}).get("brainiac_score") or 0),
            float(r.get("pool_age_hours") if r.get("pool_age_hours") is not None else 1e9),
        ),
    )

    top = scored[0] if scored else None
    if top:
        try:
            from raydium_lp1 import wallet as wallet_mod
            from raydium_lp1.scanner import assess_capacity
            from raydium_lp1.settings_io import load_settings_json
            from raydium_lp1.spend_less_get_more import annotate_brainiac_pick

            w = wallet_mod.load_wallet()
            cap = assess_capacity(scanner, w)
            bal = float((cap.get("balance") or {}).get("sol") or 0.0)
            sl_settings = load_settings_json(spath)
            top = annotate_brainiac_pick(
                top,
                deposit_usd=cfg.deposit_usd,
                balance_sol=bal,
                reserve_sol=float(getattr(scanner, "reserve_sol", 0.002) or 0.002),
                settings=sl_settings,
                scanner=scanner,
            )
        except Exception as exc:
            top = {**top, "spend_less_get_more_error": str(exc)}

    duration = round(time.time() - t0, 2)
    return {
        "scanned_at": datetime.now(UTC).isoformat(),
        "scan_status": "complete",
        "scan_duration_sec": duration,
        "scan_message": (
            f"Scanned {len(pools_raw)} pools in {duration}s; "
            f"{len(scored)} PAY/ALT candidates scored (route cap {route_cap})."
        ),
        "config": {
            "min_liquidity_usd": cfg.min_liquidity_usd,
            "deposit_usd": cfg.deposit_usd,
            "target_apr_pct": cfg.target_apr_pct,
            "scan_pages": cfg.scan_pages,
            "prefer_fee_pct": [cfg.prefer_fee_pct_min, cfg.prefer_fee_pct_max],
        },
        "pools_fetched": len(pools_raw),
        "prefiltered_count": len(prefiltered),
        "route_check_cap": route_cap,
        "candidates_scored": len(scored),
        "rejected_count": rejected,
        "errors": errors,
        "top_pick": top,
        "leaderboard": scored[:25],
        "logic_docs": LOGIC_DOCS,
        "create_pool_analysis": analyze_create_pool_feasibility(),
    }


def write_brainiac_report(report: dict[str, Any], cfg: BrainiacConfig | None = None) -> Path:
    cfg = cfg or BrainiacConfig()
    path = report_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def pick_open_target(
    report: dict[str, Any],
    cfg: BrainiacConfig,
) -> tuple[dict[str, Any] | None, str | None]:
    top = report.get("top_pick")
    if not isinstance(top, dict):
        return None, "no pool passed SUPER-BRAINIAC filters"
    best = top.get("best_strategy") if isinstance(top.get("best_strategy"), dict) else {}
    score = float(best.get("brainiac_score") or 0)
    conf = float(best.get("confidence") or 0)
    if score < cfg.min_score_to_open:
        return None, f"top score {score:.6f} below min_score_to_open"
    if conf < cfg.min_confidence:
        return None, f"confidence {conf:.2f} below min_confidence"
    return top, None


def execute_brainiac_open(
    pick: dict[str, Any],
    *,
    cfg: BrainiacConfig,
    scanner: ScannerConfig,
    force: bool = True,
    deposit_usd: float | None = None,
) -> dict[str, Any]:
    from raydium_lp1.fee_guard import FeeGuardBlockedError, reset_session_ledger
    from raydium_lp1.live_executor import open_clmm_candidate
    from raydium_lp1.settings_io import load_settings_json
    from raydium_lp1 import wallet as wallet_mod
    from raydium_lp1.scanner import assess_capacity
    from raydium_lp1.spend_less_get_more import prepare_brainiac_live_open

    pool_id = str(pick.get("pool_id") or "")
    dep = float(deposit_usd if deposit_usd is not None else cfg.deposit_usd)

    settings_path = REPO / "config" / "settings.json"
    fee_settings = dict(load_settings_json(settings_path))
    fee_settings["fee_guard_enabled"] = True
    reset_session_ledger()

    w = wallet_mod.load_wallet()
    cap = assess_capacity(scanner, w)
    bal = float((cap.get("balance") or {}).get("sol") or 0.0)
    reserve = float(getattr(scanner, "reserve_sol", 0.002) or 0.002)

    plan, strategy_id, eff_dep = prepare_brainiac_live_open(
        pick,
        deposit_usd=dep,
        balance_sol=bal,
        reserve_sol=reserve,
        settings=fee_settings,
        scanner=scanner,
    )
    if not plan.ok:
        try:
            from raydium_lp1.spend_less_get_more import enforce_open_plan

            enforce_open_plan(plan)
        except FeeGuardBlockedError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "fee_guard": True,
                "spend_less_get_more": plan.to_dict(),
            }

    sol_price = float(fee_settings.get("lp_pay_funding_sol_price_usd") or 180) or 180.0
    use_usd = float(eff_dep if eff_dep is not None else dep)
    amount_sol = use_usd / sol_price

    out = open_clmm_candidate(
        pool_id=pool_id,
        input_amount_sol=amount_sol,
        input_amount_usd=use_usd,
        force_pay_token_only=True,
        strategy_id=strategy_id,
        fee_guard_settings=fee_settings,
        sol_price_usd=sol_price,
    )
    if "spend_less_get_more" not in out:
        out["spend_less_get_more"] = plan.to_dict()
    return out


def run_brainiac_cycle(
    *,
    execute_live: bool = False,
    settings_path: Path | None = None,
    deposit_usd: float | None = None,
) -> dict[str, Any]:
    cfg, scanner = load_brainiac_config(settings_path)
    if deposit_usd is not None and float(deposit_usd) > 0:
        cfg = replace(cfg, deposit_usd=float(deposit_usd))
    report = scan_brainiac_universe(cfg=cfg, scanner=scanner)
    pick, block = pick_open_target(report, cfg)
    report["open_eligible"] = pick is not None
    report["open_block_reason"] = block
    path = write_brainiac_report(report, cfg)

    out: dict[str, Any] = {
        "ok": True,
        "report_path": str(path),
        "top_pick": pick,
        "open_block_reason": block,
        "live_open": None,
    }

    if execute_live or cfg.auto_open_live:
        if pick is None:
            out["ok"] = False
            out["error"] = block or "no pick"
        else:
            live = execute_brainiac_open(
                pick,
                cfg=cfg,
                scanner=scanner,
                deposit_usd=deposit_usd,
            )
            out["live_open"] = live
            out["ok"] = bool(live.get("ok"))
            report["live_open"] = live
            write_brainiac_report(report, cfg)
    return out
