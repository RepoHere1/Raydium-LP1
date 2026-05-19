"""Load and validate config/settings.json with actionable parse errors."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from raydium_lp1.settings_schema import KNOWN_SETTINGS_KEYS

# PowerShell ConvertTo-Json sometimes emits @{...} when -Depth is too low.
_PS_HASHTABLE_RE = re.compile(r"@\{[^}]*\}")


def read_settings_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8")


def _clean_path_value(value: Any, default: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw in {".", "./", ".\\"}:
        return default
    return raw


def sanitize_settings_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    """Fix values that break Raydium API or the scanner (empty poolType → HTTP 500)."""

    out = dict(data)
    if not str(out.get("pool_type") or "").strip():
        out["pool_type"] = "all"
    if not str(out.get("pool_sort_field") or "").strip():
        out["pool_sort_field"] = "liquidity"
    out["liquidity_history_path"] = _clean_path_value(
        out.get("liquidity_history_path"), "reports/liquidity_history.json"
    )
    out["dashboard_path"] = _clean_path_value(out.get("dashboard_path"), "reports/dashboard.json")
    out["emergency_alerts_path"] = _clean_path_value(
        out.get("emergency_alerts_path"), "reports/alerts.json"
    )
    out["rejections_csv_path"] = _clean_path_value(
        out.get("rejections_csv_path"), "reports/rejections.csv"
    )
    return out


def repair_settings_file_if_needed(path: Path) -> list[str]:
    """Persist sanitized settings when disk has known-bad values; return keys changed."""

    if not path.exists():
        return []
    text = read_settings_text(path)
    data = json.loads(text)
    if not isinstance(data, dict):
        return []
    fixed = sanitize_settings_dict(data)
    changed = sorted(k for k in fixed if data.get(k) != fixed.get(k))
    if changed:
        write_settings_json(path, fixed)
    return changed


def load_settings_json(path: Path) -> dict[str, Any]:
    """Parse settings JSON; raise ValueError with line context on failure."""

    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path.resolve()}")
    text = read_settings_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(format_json_decode_error(path, text, exc)) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be a JSON object, got {type(data).__name__}")
    if _PS_HASHTABLE_RE.search(text):
        raise ValueError(
            f"{path.resolve()} looks like it was written with PowerShell ConvertTo-Json "
            "at too low a -Depth (contains @{...} blobs). "
            "Run: .\\scripts\\repair_settings.ps1 -ApplyMomentumTemplate"
        )
    return sanitize_settings_dict(data)


def format_json_decode_error(path: Path, text: str, exc: json.JSONDecodeError) -> str:
    lines = text.splitlines()
    idx = max(exc.lineno - 1, 0)
    width = len(str(len(lines))) if lines else 1
    parts = [
        f"Invalid JSON in {path.resolve()}",
        f"  {exc.msg} (line {exc.lineno}, column {exc.colno})",
        "",
        "Nearby lines:",
    ]
    for n in range(max(0, idx - 2), min(len(lines), idx + 3)):
        marker = ">>>" if n == idx else "   "
        line_no = n + 1
        parts.append(f"  {marker} {line_no:{width}} | {lines[n]}")
    parts.extend(
        [
            "",
            "Common fixes:",
            "  • Missing comma between keys (e.g. after ] or true on the line above).",
            "  • Trailing comma after the last property (JSON does not allow it).",
            "  • // comments — remove them; only plain JSON is valid.",
            "",
            "Repair from a known-good template (backs up your file first):",
            "  .\\scripts\\repair_settings.ps1 -ApplyMomentumTemplate",
            "Or merge missing keys without rewriting everything:",
            "  .\\scripts\\sync_settings.ps1 -ApplyMomentumTemplate",
        ]
    )
    return "\n".join(parts)


def validate_settings_file(path: Path) -> tuple[bool, str]:
    try:
        load_settings_json(path)
        return True, f"OK: {path.resolve()}"
    except (OSError, ValueError) as exc:
        return False, str(exc)


def write_settings_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def merge_known_settings_patch(path: Path, patch: Mapping[str, Any]) -> dict[str, Any]:
    """Shallow-merge ``patch`` into ``path`` keeping only keys in ``KNOWN_SETTINGS_KEYS``.

    Raises:
        ValueError: unknown keys or non-object patch.
        FileNotFoundError: settings file missing.
    """

    if not isinstance(patch, Mapping):
        raise ValueError(f"PATCH must be a JSON object, not {type(patch).__name__}")
    pk = {str(k): v for k, v in patch.items()}
    known = frozenset(KNOWN_SETTINGS_KEYS)
    unknown = sorted(k for k in pk if k not in known)
    if unknown:
        raise ValueError("Unknown settings keys (not merged): " + ", ".join(unknown))
    prev = load_settings_json(path)
    merged = dict(prev)
    merged.update(pk)
    merged = sanitize_settings_dict(merged)
    write_settings_json(path, merged)
    return merged
