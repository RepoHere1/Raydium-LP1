"""Future hook: enforce max concurrent LP positions per non-quote mint.

Today the bot does not open on-chain positions; this module is a placeholder so
execution code can persist ``open_mint -> count`` without rewriting the scanner.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_SLOTS_PATH = Path("reports/lp_open_slots.json")


def policy_note(*, max_per_mint: int) -> dict[str, object]:
    """Return a JSON-serializable stub for dashboard / provenance."""

    return {
        "max_lps_per_mint": max_per_mint,
        "enforcement": "not_active_until_execution_layer",
        "state_file_hint": str(DEFAULT_SLOTS_PATH),
    }
