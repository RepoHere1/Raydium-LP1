import json
import tempfile
import unittest
from pathlib import Path

from raydium_lp1.settings_io import (
    load_settings_json,
    merge_known_settings_patch,
    repair_settings_file_if_needed,
    sanitize_settings_dict,
)


class SettingsSanitizeTests(unittest.TestCase):
    def test_empty_pool_type_becomes_all(self):
        out = sanitize_settings_dict({"pool_type": "", "min_apr": 1})
        self.assertEqual(out["pool_type"], "all")

    def test_repair_writes_all_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"pool_type": "", "min_apr": 5}) + "\n", encoding="utf-8")
            changed = repair_settings_file_if_needed(path)
            self.assertIn("pool_type", changed)
            self.assertEqual(json.loads(path.read_text())["pool_type"], "all")

    def test_merge_patch_coerces_blank_pool_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"pool_type": "all", "min_apr": 1}) + "\n", encoding="utf-8")
            merge_known_settings_patch(path, {"pool_type": "  "})
            self.assertEqual(load_settings_json(path)["pool_type"], "all")


if __name__ == "__main__":
    unittest.main()
