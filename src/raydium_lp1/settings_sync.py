"""Merge template JSON into local settings.json (stdlib only)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from raydium_lp1.settings_io import load_settings_json, write_settings_json
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

    tpl = load_settings_json(template) if template.exists() else {}
    if target.exists():
        dst = load_settings_json(target)
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
    write_settings_json(target, dst)
    return added, updated


def repair_settings(
    target: Path,
    template: Path,
    *,
    backup: bool = True,
) -> Path | None:
    """Replace target with template contents; optionally keep a .bak copy."""

    if not template.exists():
        raise FileNotFoundError(template)
    bak: Path | None = None
    if backup and target.exists():
        bak = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, bak)
    shutil.copy2(template, target)
    # Normalize formatting and validate.
    data = load_settings_json(target)
    write_settings_json(target, data)
    return bak


def normalize_settings_file(path: Path, *, output: Path | None = None) -> Path:
    """Re-read JSON and rewrite with standard formatting (fixes minor issues only)."""

    data = load_settings_json(path)
    out = output or path
    write_settings_json(out, data)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync or repair config/settings.json")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    parser.add_argument("--momentum", action="store_true", help="Use settings.momentum.example.json")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="When merging, overwrite keys from the template (momentum preset).",
    )
    parser.add_argument("--repair", action="store_true", help="Replace target from template (creates .bak)")
    parser.add_argument("--validate", action="store_true", help="Only validate target JSON")
    parser.add_argument("--normalize", type=Path, metavar="PATH", help="Rewrite PATH with standard JSON")
    parser.add_argument("--output", type=Path, help="Output path for --normalize")
    args = parser.parse_args(argv)

    template = MOMENTUM_TEMPLATE if args.momentum else args.template
    if args.validate:
        from raydium_lp1.settings_io import validate_settings_file

        ok, msg = validate_settings_file(args.target)
        print(msg)
        return 0 if ok else 1
    if args.normalize:
        normalize_settings_file(args.normalize, output=args.output)
        print(f"Wrote {args.output or args.normalize}")
        return 0
    if args.repair:
        bak = repair_settings(args.target, template, backup=True)
        if bak:
            print(f"Backed up previous file to {bak}")
        print(f"Repaired {args.target} from {template}")
        return 0
    if not args.target.exists() and template.exists():
        shutil.copy2(template, args.target)
        normalize_settings_file(args.target)
        print(f"Created {args.target} from {template}")
        return 0
    added, updated = merge_settings(
        args.target,
        template,
        overwrite_from_template=args.overwrite or args.momentum,
    )
    if added:
        print(f"Added keys: {', '.join(added)}")
    if updated:
        print(f"Updated keys: {', '.join(updated)}")
    print(f"Updated {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
