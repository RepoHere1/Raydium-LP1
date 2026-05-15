"""Per-pool decision streaming for Raydium-LP1.

This module emits one line per pool while ``scan()`` is iterating so the
user can SEE pool data being processed in real time. Column headers print
again after each Raydium API page (with ``[scan] page …``) and the same header
repeats every ``header_repeat_rows`` data rows so column labels stay aligned
with ``[PASS]`` / ``[REJ]`` lines in plain terminals.

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
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TextIO

# Strip ANSI so optional --verdict-log file stays readable in Notepad/VS Code.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)

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
    # Widen POOL_ID column for long Raydium / mint-derived ids (still capped for layout).
    pool_id_width: int = 56
    # Append plain-text copies of verdict lines here (read in another window while scan runs).
    verdict_log_path: str | None = None
    # Re-print the full table header (same column widths as data) every N rows (0 = off).
    header_repeat_rows: int = 25
    row_emit_count: int = field(default=0, repr=False)

    def out(self) -> TextIO:
        # Default stderr: matches scanner progress logs and avoids "silent"
        # runs when stdout is redirected or line-buffered differently (Windows).
        return self.stream if self.stream is not None else sys.stderr


def _pair(pool: dict) -> str:
    return f"{pool.get('mint_a_symbol', '?')}/{pool.get('mint_b_symbol', '?')}"


def _append_verdict_log(cfg: StreamConfig, *parts: str) -> None:
    path = cfg.verdict_log_path
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            for p in parts:
                fh.write(strip_ansi(p) + "\n")
    except OSError:
        pass


def append_verdict_log_plain(cfg: StreamConfig, text: str) -> None:
    """Append raw text to the verdict mirror log only (no terminal echo)."""

    path = cfg.verdict_log_path
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass


def log_between_scan_cycles(cfg: StreamConfig, *, iso_timestamp: str) -> None:
    """Mark the boundary between loop iterations in the mirror log file."""

    append_verdict_log_plain(cfg, f"\n### Next scan cycle {iso_timestamp} ###\n")


def _println_verdict(cfg: StreamConfig, line: str) -> None:
    print(line, file=cfg.out(), flush=True)
    _append_verdict_log(cfg, line)


def verdict_table_header_and_sep(cfg: StreamConfig) -> tuple[str, str]:
    """Return the same header and underline used for page headers and row reminders.

    Keeping this in one place guarantees periodic ``print_verdict_column_reminder``
    output lines up with ``_verdict_table_row`` / ``print_verdict_column_headers``.
    """

    pid_w = max(32, min(64, int(cfg.pool_id_width)))
    hdr = (
        f"{'VERDICT':<7} | {'PAIR_NAME':<26} | {'APR_PCT':>12} | "
        f"{'TVL_USD':>12} | {'VOL24_USD':>12} | {'LP_BURN':>7} | "
        f"{'POOL_ID':<{pid_w}} | REJECT_REASON"
    )
    sep = "-" * min(240, max(100, len(hdr)))
    return hdr, sep


def print_verdict_column_headers(cfg: StreamConfig, *, page: int | None = None) -> None:
    """Print a human-readable column guide (repeated each Raydium page from ``scan()``)."""

    if not cfg.enabled:
        return
    lead = f"Raydium page {page} — " if page is not None else ""
    title = f"{lead}verdict columns (full POOL_ID; REASON truncated on screen — see rejections.csv for full text)"
    if cfg.color:
        title = f"{_DIM}{title}{_RESET}"
    _println_verdict(cfg, "")
    _println_verdict(cfg, title)
    hdr, sep = verdict_table_header_and_sep(cfg)
    _println_verdict(cfg, hdr)
    _println_verdict(cfg, sep)


def _format_pool_id(raw: str, width: int) -> str:
    if len(raw) <= width:
        return raw.ljust(width)
    return (raw[: max(0, width - 3)] + "...").ljust(width)


def _verdict_table_row(verdict: str, pool: dict, reason: str | None, *, pool_id_width: int) -> str:
    apr = float(pool.get("apr") or 0)
    tvl = float(pool.get("liquidity_usd") or 0)
    vol = float(pool.get("volume_24h_usd") or 0)
    burn = pool.get("burn_percent")
    burn_col = (f"{int(burn)}%".ljust(7)) if burn is not None else " ".ljust(7)
    pair = _pair(pool)
    if len(pair) > 26:
        pair = pair[:23] + "..."
    pair = pair.ljust(26)
    pid = str(pool.get("id") or "?")
    pid_col = _format_pool_id(pid, pool_id_width)
    r = (reason or "").replace("\n", " ").replace("\r", "")
    if len(r) > 120:
        r = r[:117] + "..."
    reason_col = r if reason is not None else ""
    return (
        f"{verdict:<7} | {pair} | {apr:>12.0f} | {tvl:>12.2f} | {vol:>12.2f} | {burn_col} | "
        f"{pid_col} | {reason_col}"
    )


def print_verdict_column_reminder(cfg: StreamConfig) -> None:
    """Repeat the full column header row (same widths as data) every N rows."""

    if not cfg.enabled:
        return
    hdr, sep = verdict_table_header_and_sep(cfg)
    n = max(1, int(cfg.header_repeat_rows))
    note = (
        f"[repeat header every {n} data rows] same columns as [PASS]/[REJ] lines "
        "(POOL_ID width matches pool_id_width in StreamConfig)"
    )
    if cfg.color:
        note = f"{_DIM}{note}{_RESET}"
    _println_verdict(cfg, "")
    _println_verdict(cfg, note)
    _println_verdict(cfg, hdr)
    _println_verdict(cfg, sep)


def _maybe_repeat_header_row(cfg: StreamConfig) -> None:
    n = int(cfg.header_repeat_rows)
    if n <= 0 or not cfg.enabled:
        return
    cfg.row_emit_count += 1
    if cfg.row_emit_count % n == 0:
        print_verdict_column_reminder(cfg)


def emit_pass(pool: dict, cfg: StreamConfig) -> None:
    if not cfg.enabled or not cfg.show_passes:
        return
    pid_w = max(32, min(64, int(cfg.pool_id_width)))
    line = _verdict_table_row("[PASS]", pool, None, pool_id_width=pid_w)
    if cfg.color:
        line = f"{_GREEN}{line}{_RESET}"
    _println_verdict(cfg, line)
    _maybe_repeat_header_row(cfg)


def emit_reject(pool: dict, reasons: list[str], cfg: StreamConfig, *, idx: int = 0) -> None:
    if not cfg.enabled:
        return
    if idx >= cfg.max_rejections_shown:
        return
    reason = reasons[0] if reasons else "unspecified"
    pid_w = max(32, min(64, int(cfg.pool_id_width)))
    line = _verdict_table_row("[REJ]", pool, reason, pool_id_width=pid_w)
    if cfg.color:
        line = f"{_RED}{line}{_RESET}"
    _println_verdict(cfg, line)
    _maybe_repeat_header_row(cfg)
    if idx + 1 == cfg.max_rejections_shown:
        more = f"  ... (more rejects hidden; pass --show-rejects=N to raise the cap)"
        if cfg.color:
            more = f"{_DIM}{more}{_RESET}"
        _println_verdict(cfg, more)


def make_stream_config(
    *,
    enabled: bool = True,
    show_passes: bool = True,
    max_rejections_shown: int = 200,
    stream: TextIO | None = None,
    pool_id_width: int = 56,
    verdict_log_path: str | None = None,
    header_repeat_rows: int = 25,
) -> StreamConfig:
    target = stream if stream is not None else sys.stderr
    return StreamConfig(
        enabled=enabled,
        color=_supports_color(target),
        show_passes=show_passes,
        max_rejections_shown=max_rejections_shown,
        stream=stream,
        pool_id_width=pool_id_width,
        verdict_log_path=verdict_log_path,
        header_repeat_rows=max(0, int(header_repeat_rows)),
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
    header = f"Rejected breakdown ({total} pools):"
    if cfg.color:
        header = f"{_DIM}{header}{_RESET}"
    _println_verdict(cfg, "")
    _println_verdict(cfg, header)
    for category, count in counts.most_common():
        pct = (count / total * 100) if total else 0
        bar_width = max(1, int(round(pct / 4)))  # /4 so 100% = 25 chars
        bar = "#" * bar_width
        line = f"  {category:<26} {count:>7,} ({pct:5.1f}%)  {bar}"
        if cfg.color:
            line = f"{_RED}{line}{_RESET}" if category != "other" else f"{_DIM}{line}{_RESET}"
        _println_verdict(cfg, line)
