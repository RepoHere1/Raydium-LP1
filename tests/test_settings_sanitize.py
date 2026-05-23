import json
import tempfile
import unittest
from pathlib import Path

from raydium_lp1.settings_io import (
    load_settings_json,
    merge_known_settings_patch,
    parse_git_conflict_settings,
    repair_settings_file_if_needed,
    resolve_git_conflict_settings,
    sanitize_settings_dict,
    settings_text_has_git_conflict,
)


class SettingsSanitizeTests(unittest.TestCase):
    def test_empty_pool_type_becomes_all(self):
        out = sanitize_settings_dict({"pool_type": "", "min_apr": 1})
        self.assertEqual(out["pool_type"], "all")

    def test_empty_raydium_api_base_gets_default(self):
        out = sanitize_settings_dict({"raydium_api_base": ""})
        self.assertEqual(out["raydium_api_base"], "https://api-v3.raydium.io")

    def test_empty_report_paths_get_defaults(self):
        out = sanitize_settings_dict({"liquidity_history_path": "", "dashboard_path": "."})
        self.assertEqual(out["liquidity_history_path"], "reports/liquidity_history.json")
        self.assertEqual(out["dashboard_path"], "reports/dashboard.json")

    def test_repair_writes_all_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"pool_type": "", "min_apr": 5}) + "\n", encoding="utf-8")
            changed = repair_settings_file_if_needed(path)
            self.assertIn("pool_type", changed)
            self.assertEqual(json.loads(path.read_text())["pool_type"], "all")

    def test_git_conflict_resolves_to_valid_json(self):
        conflict = """<<<<<<< Updated upstream
{"pool_type": "all", "min_apr": 50}
=======
{"pool_type": "", "min_apr": 99}
>>>>>>> Stashed changes
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(conflict, encoding="utf-8")
            self.assertTrue(settings_text_has_git_conflict(conflict))
            parsed = parse_git_conflict_settings(conflict)
            self.assertEqual(parsed["pool_type"], "all")
            changed = resolve_git_conflict_settings(path)
            self.assertTrue(any("conflict" in c for c in changed))
            self.assertEqual(load_settings_json(path)["pool_type"], "all")

    def test_merge_patch_coerces_blank_pool_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"pool_type": "all", "min_apr": 1}) + "\n", encoding="utf-8")
            merge_known_settings_patch(path, {"pool_type": "  "})
            self.assertEqual(load_settings_json(path)["pool_type"], "all")


if __name__ == "__main__":
    unittest.main()
