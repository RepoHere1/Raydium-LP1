"""
mode_toggle — dry_run/live mode arbiter for Raydium-LP1.

- Mode lives in ``config/settings.json`` (``mode``: ``demo`` | ``live``).
- ``demo`` (displayed as DRY_RUN) syncs ``dry_run=true`` — scans use live Raydium/Jupiter/RPC reads; on-chain
  spends are blocked at ``require_live()``.
- ``live`` syncs ``dry_run=false`` — allows trade runners; dry_run→live needs confirm ``LIVE``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_SETTINGS_PATH = REPO / "config" / "settings.json"
MODE_LOG = REPO / "logs" / "mode_changes.log"

VALID_MODES = ("demo", "live")
LIVE_CONFIRM_STRING = "LIVE"


def settings_path() -> Path:
    return DEFAULT_SETTINGS_PATH


def sync_mode_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Keep ``mode`` and ``dry_run`` aligned."""

    mode = str(data.get("mode", "")).lower().strip()
    if mode not in VALID_MODES:
        mode = "demo" if bool(data.get("dry_run", True)) else "live"
    data["mode"] = mode
    data["dry_run"] = mode == "demo"
    return data


def _read_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return sync_mode_fields(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_settings(data: dict[str, Any]) -> None:
    from raydium_lp1.settings_io import write_settings_json

    write_settings_json(settings_path(), sync_mode_fields(dict(data)))


def _log_mode_change(old: str, new: str, source: str) -> None:
    try:
        MODE_LOG.parent.mkdir(exist_ok=True)
        with open(MODE_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {old} -> {new}  via {source}\n")
    except Exception:
        pass


def get_mode() -> str:
    return str(_read_settings().get("mode", "demo"))


def is_live() -> bool:
    return get_mode() == "live"


def is_demo() -> bool:
    return get_mode() == "demo"


class ModeBlockedError(Exception):
  pass


class ModeChangeError(Exception):
    pass


def require_live(reason: str = "on-chain operation") -> None:
    if not is_live():
        raise ModeBlockedError(
            f"DRY_RUN MODE — {reason} blocked at wallet boundary. "
            "Switch to LIVE on the dashboard (type LIVE to confirm)."
        )


def set_mode(new_mode: str, confirm: str | None = None, source: str = "api") -> dict[str, Any]:
    new_mode = str(new_mode).lower().strip()
    if new_mode not in VALID_MODES:
        raise ModeChangeError(f"invalid mode {new_mode!r}, must be demo or live")

    old = get_mode()
    if old == new_mode:
        return {"ok": True, "mode": new_mode, "unchanged": True, "dry_run": new_mode == "demo"}

    if old == "demo" and new_mode == "live" and confirm != LIVE_CONFIRM_STRING:
        raise ModeChangeError(
            f"dry_run -> live requires confirm={LIVE_CONFIRM_STRING!r} (got {confirm!r})"
        )

    s = _read_settings()
    s["mode"] = new_mode
    s = sync_mode_fields(s)
    changes = s.setdefault("mode_changes", [])
    if isinstance(changes, list):
        changes.append({"ts": time.time(), "old": old, "new": new_mode, "source": source})
        s["mode_changes"] = changes[-50:]
    _write_settings(s)
    _log_mode_change(old, new_mode, source)
    return {"ok": True, "mode": new_mode, "previous": old, "dry_run": s["dry_run"]}


def status() -> dict[str, Any]:
    s = _read_settings()
    return {
        "mode": get_mode(),
        "dry_run": bool(s.get("dry_run", True)),
        "banner": banner(),
        "settings_path": str(settings_path().resolve()),
    }


def banner() -> str:
    if is_live():
        return "*** LIVE — dry_run off; on-chain spends allowed where trade code calls require_live() ***"
    return "DRY_RUN — live market data; on-chain spends blocked (type LIVE on dashboard to arm real trades)."


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=2))
    elif cmd == "to-demo":
        print(json.dumps(set_mode("demo", source="cli"), indent=2))
    elif cmd == "to-live":
        confirm = sys.argv[2] if len(sys.argv) > 2 else None
        try:
            print(json.dumps(set_mode("live", confirm=confirm, source="cli"), indent=2))
        except ModeChangeError as e:
            print(json.dumps({"ok": False, "error": str(e)}, indent=2))
            sys.exit(2)
    else:
        print("usage: python -m raydium_lp1.mode_toggle [status|to-demo|to-live LIVE]")
        sys.exit(2)
