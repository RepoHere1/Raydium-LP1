"""Load and validate config/settings.json with actionable parse errors."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# PowerShell ConvertTo-Json sometimes emits @{...} when -Depth is too low.
_PS_HASHTABLE_RE = re.compile(r"@\{[^}]*\}")


def read_settings_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8")


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
    return data


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
