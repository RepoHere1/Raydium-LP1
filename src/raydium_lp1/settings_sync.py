"""Merge template JSON into local settings.json (stdlib only)."""

from __future__ import annotations

import json
from pathlib import Path

from raydium_lp1.settings_schema import KNOWN_SETTINGS_KEYS

DEFAULT_TARGET = Path("config/settings.json")
TEMPLATE = Path("config/settings.example.json")
MOMENTUM_TEMPLATE = Path("config/settings.momentum.example.json")


def merge_settings(
    target: Path,
    template: Path,
    *,
    overwrite_from_template: bool = False,
) -> tuple[list[str], list[str]]:
    """Return (added_keys, updated_keys)."""

    tpl = json.loads(template.read_text(encoding="utf-8")) if template.exists() else {}
    if target.exists():
        dst = json.loads(target.read_text(encoding="utf-8"))
    else:
        dst = {}
    added: list[str] = []
    updated: list[str] = []
    for key in KNOWN_SETTINGS_KEYS:
        if key not in tpl and key not in dst:
            continue
        if key not in dst and key in tpl:
            dst[key] = tpl[key]
            added.append(key)
        elif overwrite_from_template and key in tpl:
            if dst.get(key) != tpl[key]:
                dst[key] = tpl[key]
                updated.append(key)
    # Preserve unknown user keys
    for key, value in tpl.items():
        if str(key).startswith("_"):
            continue
        if key not in dst:
            dst[key] = value
            if key not in added:
                added.append(str(key))
        elif overwrite_from_template:
            dst[key] = value
            if str(key) not in updated:
                updated.append(str(key))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dst, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return added, updated
