"""Map dashboard LP strategy settings → Raydium CLMM ``open_position`` params + display labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from raydium_lp1.lp_order_strategies import (
    STRATEGY_ASYMMETRIC,
    STRATEGY_AUTO,
    STRATEGY_CENTERED_TIGHT,
    STRATEGY_FULL_RANGE,
    STRATEGY_TRAILING_SKEW,
    build_open_order,
    get_strategy,
)


def _band_tick_steps(width_pct: float) -> int:
    w = max(4.0, float(width_pct))
    return int(max(8, min(32, round(6 + w * 0.45))))


@dataclass(frozen=True)
class LiveOpenStyle:
    """Resolved CLMM open parameters for one LIVE deposit."""

    pool_type: str
    strategy_id: str
    strategy_label: str
    placement: str  # single_above | single_below | centered | full_range
    width_pct: float
    open_kwargs: dict[str, Any]
    lp_style_key: str
    lp_style_label: str

    def to_position_fields(self) -> dict[str, Any]:
        return {
            "lp_pool_type": self.pool_type,
            "lp_strategy_id": self.strategy_id,
            "lp_strategy_label": self.strategy_label,
            "lp_placement": self.placement,
            "lp_width_pct": self.width_pct,
            "lp_style_key": self.lp_style_key,
            "lp_style_label": self.lp_style_label,
            "lp_open_params": dict(self.open_kwargs),
        }


def resolve_live_open_style(
    config: Any,
    pool: Mapping[str, Any],
    *,
    momentum: Mapping[str, Any] | None = None,
) -> LiveOpenStyle:
    """Turn ``lp_active_strategy`` (+ pool momentum) into ``raydium_clmm.open_position`` kwargs."""

    mom = momentum if isinstance(momentum, Mapping) else pool.get("momentum")
    mom_dict = dict(mom) if isinstance(mom, Mapping) else None
    strategy_id = str(getattr(config, "lp_active_strategy", STRATEGY_AUTO) or STRATEGY_AUTO)
    default_w = float(getattr(config, "lp_default_range_width_pct", 20.0) or 20.0)
    skew_mom = bool(getattr(config, "lp_skew_use_momentum", True))

    plan = build_open_order(
        pool,
        mom_dict,
        strategy_id=strategy_id,
        default_width_pct=default_w,
        skew_use_momentum=skew_mom,
    )
    sid = str(plan.get("strategy_id") or strategy_id)
    spec = get_strategy(sid) or get_strategy(STRATEGY_AUTO)
    assert spec is not None
    width = float(plan.get("width_pct") or default_w)
    skew = float(plan.get("skew") or 0.0)
    band = plan.get("band") if isinstance(plan.get("band"), dict) else {}
    steps = _band_tick_steps(width)

    placement = "centered"
    open_kwargs: dict[str, Any]

    if sid == STRATEGY_FULL_RANGE:
        placement = "full_range"
        open_kwargs = {
            "single_side": None,
            "tick_lower_pct_below": 45.0,
            "tick_upper_pct_above": 45.0,
            "band_tick_steps": max(steps, 28),
        }
    elif sid == STRATEGY_ASYMMETRIC or (
        sid == STRATEGY_TRAILING_SKEW and abs(skew) >= 0.08
    ):
        order_type = str(band.get("order_type") or ("bullish" if skew >= 0 else "bearish")).lower()
        if order_type in ("bullish", "above", "sell"):
            placement = "single_above"
            open_kwargs = {
                "single_side": "above",
                "single_side_start_pct": 0.5,
                "single_side_width_pct": width,
                "band_tick_steps": steps,
            }
        else:
            placement = "single_below"
            open_kwargs = {
                "single_side": "below",
                "single_side_start_pct": 0.5,
                "single_side_width_pct": width,
                "band_tick_steps": steps,
            }
    elif sid == STRATEGY_CENTERED_TIGHT:
        half = max(3.0, width / 2.0)
        placement = "centered"
        open_kwargs = {
            "single_side": None,
            "tick_lower_pct_below": half,
            "tick_upper_pct_above": half,
            "band_tick_steps": steps,
        }
    else:
        half = max(4.0, width / 2.0)
        if abs(skew) >= 0.35 and skew_mom:
            placement = "single_above" if skew > 0 else "single_below"
            open_kwargs = {
                "single_side": "above" if skew > 0 else "below",
                "single_side_start_pct": 0.5,
                "single_side_width_pct": width,
                "band_tick_steps": steps,
            }
        else:
            placement = "centered"
            open_kwargs = {
                "single_side": None,
                "tick_lower_pct_below": half,
                "tick_upper_pct_above": half,
                "band_tick_steps": steps,
            }

    place_human = {
        "single_above": "single above",
        "single_below": "single below",
        "centered": "centered",
        "full_range": "full range",
    }.get(placement, placement)
    label = f"CLMM · {place_human} · {width:.0f}% · {spec.short_label}"
    key = f"{sid}|{placement}|w{int(round(width))}"

    return LiveOpenStyle(
        pool_type="CLMM",
        strategy_id=sid,
        strategy_label=spec.short_label,
        placement=placement,
        width_pct=round(width, 2),
        open_kwargs=open_kwargs,
        lp_style_key=key,
        lp_style_label=label,
    )


def infer_style_from_clmm_result(clmm: Mapping[str, Any], *, strategy_id: str = "") -> dict[str, str]:
    """Backfill labels for positions opened before style metadata was stored."""

    mode = str(clmm.get("single_side_mode") or "").lower()
    width = float(clmm.get("single_side_width_pct") or 15.0)
    steps = int(clmm.get("band_tick_steps") or 10)
    if mode == "above":
        placement = "single_above"
    elif mode == "below":
        placement = "single_below"
    elif mode in ("", "none", "null"):
        placement = "centered"
    else:
        placement = mode or "centered"
    sid = strategy_id or "legacy_hardcoded"
    spec = get_strategy(sid) if strategy_id else None
    short = spec.short_label if spec else "single above (legacy)"
    if not strategy_id and mode == "above":
        short = "legacy default"
    label = f"CLMM · {placement.replace('_', ' ')} · {width:.0f}% · {short}"
    key = f"{sid}|{placement}|w{int(round(width))}|s{steps}"
    return {"lp_style_key": key, "lp_style_label": label, "lp_placement": placement}


def annotate_position_style(row: dict[str, Any], config: Any | None = None) -> dict[str, Any]:
    """Ensure ``lp_style_label`` exists on a live position row (mutates copy)."""

    out = dict(row)
    if out.get("lp_style_label"):
        return out
    clmm = out.get("clmm_result") if isinstance(out.get("clmm_result"), dict) else {}
    sid = str(out.get("lp_strategy_id") or "")
    inferred = infer_style_from_clmm_result(clmm, strategy_id=sid)
    out.update(inferred)
    if config is not None and not out.get("lp_strategy_id"):
        try:
            style = resolve_live_open_style(config, out, momentum=out.get("momentum"))
            out.update(style.to_position_fields())
        except Exception:
            pass
    out.setdefault("lp_pool_type", "CLMM")
    if clmm:
        lo, hi, cur = clmm.get("tick_lower"), clmm.get("tick_upper"), clmm.get("tick_current")
        if lo is not None and hi is not None and cur is not None:
            try:
                in_rng = int(lo) <= int(cur) <= int(hi)
                out["in_range_at_open"] = in_rng
                out["out_of_range_at_open"] = not in_rng
            except (TypeError, ValueError):
                pass
    return out


def annotate_live_positions(rows: list[dict[str, Any]], config: Any | None = None) -> list[dict[str, Any]]:
    return [annotate_position_style(r, config) for r in rows if isinstance(r, dict)]
