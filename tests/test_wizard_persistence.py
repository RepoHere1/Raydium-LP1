"""Verify that RPC URLs persist across wizard runs.

The user reported the wizard 'forgets' RPC entries between runs. The new
wizard saves them into BOTH .env and config/settings.json. This test
simulates that workflow purely on the Python side: write a settings.json
the way the wizard does, then prove ScannerConfig.from_file() reloads
all of those URLs as solana_rpc_urls.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1.scanner import ScannerConfig, load_dotenv


class WizardPersistenceTests(unittest.TestCase):
    def test_rpc_urls_round_trip_through_settings_json(self):
        primary = "https://api.mainnet-beta.solana.com"
        chainstack = "https://solana-mainnet.core.chainstack.com/abc123"
        onfinality = "https://onfinality.io/networks/solana"
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "settings.json"
            config_path.write_text(json.dumps({
                "dry_run": True,
                "strategy": "degen",
                "min_apr": 100,
                "solana_rpc_urls": [primary, chainstack, onfinality],
            }))
            # Simulate a fresh environment: no env vars set.
            with patch.dict(os.environ, {}, clear=True):
                config = ScannerConfig.from_file(config_path)
        self.assertIn(primary, config.solana_rpc_urls)
        self.assertIn(chainstack, config.solana_rpc_urls)
        self.assertIn(onfinality, config.solana_rpc_urls)

    def test_env_and_config_rpcs_combined_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "SOLANA_RPC_URL=https://api.mainnet-beta.solana.com\n"
                "SOLANA_RPC_URLS=https://solana-rpc.publicnode.com,https://solana.drpc.org\n",
                encoding="utf-8",
            )
            config_path = Path(tmp) / "settings.json"
            config_path.write_text(json.dumps({
                "min_apr": 100,
                "solana_rpc_urls": [
                    "https://api.mainnet-beta.solana.com",  # duplicate of env primary
                    "https://onfinality.io/networks/solana",
                ],
            }))
            with patch.dict(os.environ, {}, clear=True):
                load_dotenv(env_path)
                config = ScannerConfig.from_file(config_path)
        # Duplicate primary appears only once.
        self.assertEqual(
            config.solana_rpc_urls.count("https://api.mainnet-beta.solana.com"), 1
        )
        # Both backup and config-only URLs are present.
        self.assertIn("https://solana-rpc.publicnode.com", config.solana_rpc_urls)
        self.assertIn("https://onfinality.io/networks/solana", config.solana_rpc_urls)


if __name__ == "__main__":
    unittest.main()
