import json
import tempfile
import unittest
from pathlib import Path

from raydium_lp1.settings_io import (
    load_settings_json,
    merge_known_settings_patch,
    write_settings_json,
)
from raydium_lp1.settings_sync import merge_settings, repair_settings
from raydium_lp1.scanner import ScannerConfig


class SettingsIoTests(unittest.TestCase):
    def test_missing_comma_shows_context(self) -> None:
        bad = '{\n  "a": 1\n  "b": 2\n}\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(bad, encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_settings_json(path)
            msg = str(ctx.exception)
            self.assertIn("line 3", msg)
            self.assertIn("repair_settings", msg)

    def test_repair_from_momentum_template(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        template = repo / "config" / "settings.momentum.example.json"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            target.write_text('{"strategy": "momentum",\n"min_apr": 1\n}\n', encoding="utf-8")
            bak = repair_settings(target, template, backup=True)
            self.assertIsNotNone(bak)
            data = load_settings_json(target)
            self.assertEqual(data["strategy"], "momentum")
            ScannerConfig.from_file(target)

    def test_merge_writes_valid_json(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        template = repo / "config" / "settings.momentum.example.json"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            target.write_text(json.dumps({"dry_run": True, "strategy": "custom"}) + "\n", encoding="utf-8")
            merge_settings(target, template, overwrite_from_template=False)
            load_settings_json(target)


class MergeKnownSettingsPatchTests(unittest.TestCase):
    def test_merges_known_keys_and_preserves_extras(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            write_settings_json(p, {"dry_run": True, "min_apr": 100.0, "_readme": "x"})
            merged = merge_known_settings_patch(p, {"min_apr": 50.0, "pages": 3})
            self.assertEqual(merged["min_apr"], 50.0)
            self.assertEqual(merged["pages"], 3)
            self.assertEqual(merged["_readme"], "x")
            data = load_settings_json(p)
            self.assertEqual(data["min_apr"], 50.0)
            self.assertEqual(data["pages"], 3)

    def test_unknown_patch_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            p.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                merge_known_settings_patch(p, {"not_a_real_setting": 1})
            self.assertIn("Unknown settings keys", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
