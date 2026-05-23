import json
import tempfile
import time
import unittest
from pathlib import Path

from raydium_lp1.scanner import ScannerConfig, _reload_config_if_changed
from raydium_lp1.settings_io import write_settings_json


class ConfigReloadTests(unittest.TestCase):
    def test_reload_config_if_changed_reads_new_hard_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            write_settings_json(
                path,
                {
                    "min_apr": 100,
                    "min_liquidity_usd": 10,
                    "min_volume_24h_usd": 10,
                    "hard_exit_min_tvl_usd": 200.0,
                    "require_sell_route": False,
                    "pages": 1,
                    "page_size": 100,
                },
            )
            cfg = ScannerConfig.from_file(path)
            mtime = path.stat().st_mtime
            time.sleep(0.02)
            write_settings_json(
                path,
                {
                    "min_apr": 100,
                    "min_liquidity_usd": 10,
                    "min_volume_24h_usd": 10,
                    "hard_exit_min_tvl_usd": 0.0,
                    "require_sell_route": False,
                    "pages": 1,
                    "page_size": 100,
                },
            )
            new_cfg, new_mtime = _reload_config_if_changed(path, cfg, mtime)
            self.assertGreater(new_mtime, mtime)
            self.assertEqual(new_cfg.hard_exit_min_tvl_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
