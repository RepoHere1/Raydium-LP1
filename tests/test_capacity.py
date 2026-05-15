import unittest
from unittest.mock import patch

from raydium_lp1 import wallet
from raydium_lp1.scanner import ScannerConfig, assess_capacity, scan


VALID_ADDRESS = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


class CapacityTests(unittest.TestCase):
    def test_compute_capacity_floors_division(self):
        cap = wallet.compute_capacity(0.55, position_size_sol=0.1, reserve_sol=0.02)
        # 0.55 - 0.02 = 0.53 ; floor(0.53 / 0.1) = 5
        self.assertEqual(cap.max_positions, 5)
        self.assertEqual(cap.reserved_sol, 0.02)
        self.assertAlmostEqual(cap.available_sol, 0.53)

    def test_zero_balance_zero_capacity(self):
        cap = wallet.compute_capacity(0.0, position_size_sol=0.1)
        self.assertEqual(cap.max_positions, 0)

    def test_invalid_position_size_raises(self):
        with self.assertRaises(wallet.WalletError):
            wallet.compute_capacity(1.0, position_size_sol=0)

    def test_fetch_sol_balance_parses_rpc_response(self):
        calls = []

        def fake_rpc(url, payload):
            calls.append((url, payload))
            return {"jsonrpc": "2.0", "id": 1, "result": {"context": {"slot": 1}, "value": 1_234_567_890}}

        result = wallet.fetch_sol_balance(VALID_ADDRESS, ["https://rpc.example"], rpc_post=fake_rpc)
        self.assertTrue(result.ok)
        self.assertEqual(result.lamports, 1_234_567_890)
        self.assertAlmostEqual(result.sol, 1.23456789, places=6)
        self.assertEqual(calls[0][1]["method"], "getBalance")

    def test_fetch_sol_balance_fails_over_to_next_rpc(self):
        attempts = []

        def fake_rpc(url, payload):
            attempts.append(url)
            if "bad" in url:
                raise RuntimeError("nope")
            return {"result": {"value": 5_000_000_000}}

        result = wallet.fetch_sol_balance(
            VALID_ADDRESS,
            ["https://bad.example", "https://good.example"],
            rpc_post=fake_rpc,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.lamports, 5_000_000_000)
        self.assertEqual(result.rpc_url, "https://good.example")
        self.assertEqual(attempts, ["https://bad.example", "https://good.example"])

    def test_fetch_sol_balance_all_failed_returns_error(self):
        def fake_rpc(url, payload):
            raise RuntimeError("everything is down")

        result = wallet.fetch_sol_balance(VALID_ADDRESS, ["https://bad.example"], rpc_post=fake_rpc)
        self.assertFalse(result.ok)
        self.assertIn("everything is down", result.error)


class ScannerCapacityIntegrationTests(unittest.TestCase):
    def _api_response(self, n: int) -> dict:
        return {
            "data": {
                "data": [
                    {
                        "id": f"pool-{i}",
                        "apr24h": 1500,
                        "tvl": 5000,
                        "volume24h": 1000,
                        "mintA": {"symbol": "SOL", "address": "solmint"},
                        "mintB": {"symbol": f"TKN{i}", "address": f"mint-{i}"},
                    }
                    for i in range(n)
                ]
            }
        }

    def test_capacity_caps_candidates_returned(self):
        wcfg = wallet.override_wallet(VALID_ADDRESS)
        # 0.32 - 0.02 reserve = 0.30 ; / 0.1 = 3 positions
        def fake_rpc(url, payload):
            return {"result": {"value": int(0.32 * wallet.LAMPORTS_PER_SOL)}}

        config = ScannerConfig(
            min_apr=100,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            require_sell_route=False,
            track_liquidity_health=False,
            position_size_sol=0.1,
            reserve_sol=0.02,
            solana_rpc_urls=["https://rpc.example"],
        )
        with patch("raydium_lp1.scanner.fetch_json", return_value=self._api_response(10)):
            report = scan(config, wallet_config=wcfg, rpc_post=fake_rpc)
        self.assertEqual(report["candidate_count"], 3)
        self.assertEqual(report["candidate_count_pre_capacity"], 10)
        self.assertEqual(report["candidates_truncated"], 7)
        self.assertEqual(report["wallet_capacity"]["capacity"]["max_positions"], 3)

    def test_no_wallet_means_no_cap(self):
        config = ScannerConfig(
            min_apr=100,
            min_liquidity_usd=10,
            min_volume_24h_usd=10,
            require_sell_route=False,
            track_liquidity_health=False,
        )
        with patch("raydium_lp1.scanner.fetch_json", return_value=self._api_response(5)):
            report = scan(config)
        self.assertEqual(report["candidate_count"], 5)
        self.assertEqual(report["candidates_truncated"], 0)
        self.assertIsNone(report["wallet_capacity"]["wallet"])

    def test_assess_capacity_with_dead_rpcs_returns_zero_capacity(self):
        wcfg = wallet.override_wallet(VALID_ADDRESS)

        def fake_rpc(url, payload):
            raise RuntimeError("dead")

        config = ScannerConfig(position_size_sol=0.1, solana_rpc_urls=["https://x"])
        info = assess_capacity(config, wcfg, rpc_post=fake_rpc)
        self.assertFalse(info["balance"]["ok"])
        self.assertEqual(info["capacity"]["max_positions"], 0)


if __name__ == "__main__":
    unittest.main()
