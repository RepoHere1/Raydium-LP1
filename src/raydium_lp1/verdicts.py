"""Per-pool decision streaming for Raydium-LP1.

This module emits one line per pool while ``scan()`` is iterating so the
user can SEE pool data being processed in real time:

    [PASS] SOL/MEME    APR  1500%  TVL $   8500  Vol $ 2500  pool=good-pool
    [REJ ] SOL/RUG     APR  4000%  TVL $    800  Vol $    5  reason=...

Lines are green/red where the terminal supports ANSI colors (Windows 10+
PowerShell, Linux/macOS terminals). By default lines go to **stderr** so they
stay with ``[scan] page …`` progress (some Windows hosts buffer or separate
``stdout``). Use ``--quiet`` to suppress the stream; ``--verdict-stdout`` sends
it back to stdout for piping. The rejection breakdown uses the same stream.

The breakdown counts rejected pools by first-listed reason so the user
can dial in their filters ("oh, 24800 pools fell to the APR filter — I
should lower it / pick a different sort field").
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from dataclasses import dataclass
from typing import TextIO

# ANSI escape codes. We probe stdout to decide whether to emit them.
_GREEN = "\033[32m"
_RED = "\033[31m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("RAYDIUM_LP1_FORCE_COLOR"):
        return True
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    # Windows 10+ PowerShell understands ANSI in modern terminals.
    return True


@dataclass
class StreamConfig:
    enabled: bool = True
    color: bool = True
    show_passes: bool = True
    max_rejections_shown: int = 200
    stream: TextIO | None = None

    def out(self) -> TextIO:
        # Default stderr: matches scanner progress logs and avoids "silent"
        # runs when stdout is redirected or line-buffered differently (Windows).
        return self.stream if self.stream is not None else sys.stderr


def _pair(pool: dict) -> str:
    return f"{pool.get('mint_a_symbol', '?')}/{pool.get('mint_b_symbol', '?')}"


def _summary_line(pool: dict) -> str:
    apr = float(pool.get("apr") or 0)
    tvl = float(pool.get("liquidity_usd") or 0)
    vol = float(pool.get("volume_24h_usd") or 0)
    burn = pool.get("burn_percent")
    burn_part = f" burn={int(burn)}%" if burn is not None else ""
    return (
        f"{_pair(pool):<22} "
        f"APR {apr:>9,.0f}%  "
        f"TVL ${tvl:>10,.0f}  "
        f"Vol ${vol:>9,.0f}{burn_part}  "
        f"pool={pool.get('id', '?')[:8]}"
    )


def emit_pass(pool: dict, cfg: StreamConfig) -> None:
    if not cfg.enabled or not cfg.show_passes:
        return
    line = f"[PASS] {_summary_line(pool)}"
    if cfg.color:
        line = f"{_GREEN}{line}{_RESET}"
    print(line, file=cfg.out(), flush=True)


def emit_reject(pool: dict, reasons: list[str], cfg: StreamConfig, *, idx: int = 0) -> None:
    if not cfg.enabled:
        return
    if idx >= cfg.max_rejections_shown:
        return
    reason = reasons[0] if reasons else "unspecified"
    line = f"[REJ ] {_summary_line(pool)}  reason={reason}"
    if cfg.color:
        line = f"{_RED}{line}{_RESET}"
    print(line, file=cfg.out(), flush=True)
    if idx + 1 == cfg.max_rejections_shown:
        more = f"  ... (more rejects hidden; pass --show-rejects=N to raise the cap)"
        if cfg.color:
            more = f"{_DIM}{more}{_RESET}"
        print(more, file=cfg.out(), flush=True)


def make_stream_config(
    *,
    enabled: bool = True,
    show_passes: bool = True,
    max_rejections_shown: int = 200,
    stream: TextIO | None = None,
) -> StreamConfig:
    target = stream if stream is not None else sys.stderr
    return StreamConfig(
        enabled=enabled,
        color=_supports_color(target),
        show_passes=show_passes,
        max_rejections_shown=max_rejections_shown,
        stream=stream,
    )


def _classify_reason(reason: str) -> str:
    """Map an individual reason to a small set of categories for the breakdown."""

    r = reason.lower()
    if r.startswith("hard reject") or "exit-safety line" in r:
        return "hard_exit_red_line"
    if "price impact" in r or ("jupiter" in r and "impact" in r):
        return "price_impact_too_high"
    if r.startswith("apr "):
        return "apr_below_threshold"
    if r.startswith("liquidity "):
        return "tvl_below_threshold"
    if "volume" in r:
        return "volume_below_threshold"
    if "quote symbol" in r:
        return "quote_symbol_not_allowed"
    if "blocked" in r:
        return "blocked_list"
    if "sell route" in r or "no sell route" in r:
        return "no_sell_route"
    if "pool id" in r:
        return "missing_pool_id"
    if "pool age" in r:
        return "pool_age"
    if "burn" in r:
        return "lp_burn_too_low"
    return "other"


def summarize_rejections(rejected: list[dict]) -> Counter:
    """Group rejected pools by the category of their first reason."""

    counts: Counter = Counter()
    for entry in rejected:
        reasons = entry.get("reasons") or []
        category = _classify_reason(reasons[0]) if reasons else "other"
        counts[category] += 1
    return counts


def print_rejection_breakdown(rejected_or_counts, cfg: StreamConfig) -> None:
    """Accept either a list of rejected pool dicts OR a precomputed counts dict."""

    if isinstance(rejected_or_counts, dict):
        counts = Counter(rejected_or_counts)
    elif rejected_or_counts:
        counts = summarize_rejections(rejected_or_counts)
    else:
        return
    if not counts:
        return
    total = sum(counts.values())
    out = cfg.out()
    header = f"Rejected breakdown ({total} pools):"
    if cfg.color:
        header = f"{_DIM}{header}{_RESET}"
    print("", file=out)
    print(header, file=out)
    for category, count in counts.most_common():
        pct = (count / total * 100) if total else 0
        bar_width = max(1, int(round(pct / 4)))  # /4 so 100% = 25 chars
        bar = "#" * bar_width
        line = f"  {category:<26} {count:>7,} ({pct:5.1f}%)  {bar}"
        if cfg.color:
            line = f"{_RED}{line}{_RESET}" if category != "other" else f"{_DIM}{line}{_RESET}"
        print(line, file=out, flush=True)
