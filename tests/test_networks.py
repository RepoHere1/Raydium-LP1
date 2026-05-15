import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raydium_lp1 import networks
from raydium_lp1.scanner import ScannerConfig, assess_capacity, scan
from tests.scan_test_defaults import RAYDIUM_CPMM_PROGRAM, SCAN_TEST_DISABLE_VERIFY


VALID_ADDRESS = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


class NetworkAdapterTests(unittest.TestCase):
    def test_default_solana_adapter_is_live(self):
        adapter = networks.get_adapter("solana")
        self.assertEqual(adapter.key, "solana")
        self.assertTrue(adapter.supports_live)

    def test_ethereum_adapter_is_stub(self):
        adapter = networks.get_adapter("ethereum")
        self.assertEqual(adapter.key, "ethereum")
        self.assertFalse(adapter.supports_live)
        with self.assertRaises(networks.NetworkNotSupportedError):
            adapter.fetch_native_balance("0xabc", ["https://x"])
        with self.assertRaises(networks.NetworkNotSupportedError):
            adapter.swap_quote_url("a", "b", 1, 100)

    def test_base_adapter_is_stub(self):
        adapter = networks.get_adapter("base")
        self.assertFalse(adapter.supports_live)

    def test_normalize_network_rejects_unknown(self):
        with self.assertRaises(ValueError):
            networks.normalize_network("dogecoin")

    def test_solana_quote_url_has_required_params(self):
        adapter = networks.get_adapter("solana")
        url = adapter.swap_quote_url("MINTA", "MINTB", 100, 50)
        self.assertIn("inputMint=MINTA", url)
        self.assertIn("outputMint=MINTB", url)
        self.assertIn("amount=100", url)
        self.assertIn("slippageBps=50", url)

    def test_solana_adapter_uses_injected_rpc(self):
        adapter = networks.SolanaAdapter(rpc_post=lambda url, payload: {"result": {"value": 1_000_000_000}})
        result = adapter.fetch_native_balance(VALID_ADDRESS, ["https://x"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["lamports"], 1_000_000_000)


class MultiNetworkScannerTests(unittest.TestCase):
    def test_non_live_network_short_circuits_scan(self):
        config = ScannerConfig(network="ethereum", require_sell_route=False, track_liquidity_health=False)
        with patch("raydium_lp1.scanner.fetch_json") as mocked_fetch:
            report = scan(config)
            mocked_fetch.assert_not_called()
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["network"], "ethereum")
        self.assertIn("notice", report)
        self.assertIn("not live", report["notice"])

    def test_assess_capacity_skips_balance_on_stub_network(self):
        from raydium_lp1 import wallet
        wcfg = wallet.override_wallet(VALID_ADDRESS)
        config = ScannerConfig(network="base", solana_rpc_urls=["https://x"])
        info = assess_capacity(config, wcfg, rpc_post=lambda *_: {"result": {"value": 100}})
        self.assertEqual(info["network"]["key"], "base")
        self.assertFalse(info["balance"]["ok"])
        self.assertIn("stub-only", info["balance"]["error"])
        self.assertEqual(info["capacity"]["max_positions"], 0)

    def test_solana_network_still_uses_raydium_api(self):
        api_response = {
            "data": {"data": [{
                "id": "pool-1",
                "programId": RAYDIUM_CPMM_PROGRAM,
                "apr24h": 1500, "tvl": 5000, "volume24h": 1000,
                "mintA": {"symbol": "SOL", "address": "solmint"},
                "mintB": {"symbol": "TKN", "address": "tknmint"},
            }]}
        }
        config = ScannerConfig(
            min_apr=100, min_liquidity_usd=10, min_volume_24h_usd=10,
            require_sell_route=False, track_liquidity_health=False,
            network="solana",
            **SCAN_TEST_DISABLE_VERIFY,
        )
        with patch("raydium_lp1.scanner.fetch_json", return_value=api_response):
            report = scan(config)
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["network"], "solana")


if __name__ == "__main__":
    unittest.main()
