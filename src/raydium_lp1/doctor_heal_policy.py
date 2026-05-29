"""When raydium_doctor may auto-repair files (heal mode).

Default: heal ON (fix BOM, merge markers, truncated JSON seeds, etc.).
Heal OFF when an AI/agent is editing the tree, or when explicitly disabled.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

AI_EDIT_ENV_KEYS = (
    "RAYDIUM_LP1_AI_EDIT",
    "CURSOR_AGENT",
    "CURSOR_AI_EDIT",
)


def ai_edit_in_progress() -> bool:
    for key in AI_EDIT_ENV_KEYS:
        if os.environ.get(key, "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    marker = REPO / ".raydium_lp1_ai_edit"
    if marker.is_file():
        return True
    cursor_flag = REPO / ".cursor" / "raydium_lp1_ai_edit"
    return cursor_flag.is_file()


def should_auto_heal(*, cli_heal: bool = False, cli_no_heal: bool = False) -> bool:
    if cli_no_heal or os.environ.get("RAYDIUM_LP1_DOCTOR_NO_HEAL", "").strip() in ("1", "true", "yes"):
        return False
    if cli_heal or os.environ.get("RAYDIUM_LP1_DOCTOR_HEAL", "").strip() in ("1", "true", "yes"):
        return True
    if ai_edit_in_progress():
        return False
    # Legacy opt-in flag from early stack scripts (still respected if set to 0)
    if os.environ.get("STACK_DOCTOR_HEAL", "").strip() in ("0", "false", "no"):
        return False
    return True
