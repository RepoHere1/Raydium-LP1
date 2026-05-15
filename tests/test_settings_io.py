import json
import tempfile
import unittest
from pathlib import Path

from raydium_lp1.settings_io import load_settings_json
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


if __name__ == "__main__":
    unittest.main()
