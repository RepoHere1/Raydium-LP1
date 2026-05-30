import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from raydium_lp1.manual_live_open import (
    ManualLiveBlockedError,
    assert_manual_live_open_allowed,
    notify_manual_live_blocked,
)


def _pool(*, liq: float = 500.0) -> dict:
    return {
        "id": "PoolTest123",
        "mint_a_symbol": "SOL",
        "mint_b_symbol": "MEME",
        "mint_a": "So11111111111111111111111111111111111111112",
        "mint_b": "MemeMint1111111111111111111111111111111111",
        "liquidity_usd": liq,
    }


class ManualLiveOpenTests(unittest.TestCase):
    def test_skipped_when_not_explicit_pool_id(self) -> None:
        cfg = SimpleNamespace(manual_live_min_pool_liquidity_usd=1000.0)
        out = assert_manual_live_open_allowed(_pool(liq=10), cfg, explicit_pool_id=False)
        self.assertTrue(out.get("skipped"))

    def test_blocks_low_liquidity_and_writes_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alerts = Path(tmp) / "alerts.json"
            cfg = SimpleNamespace(
                manual_live_min_pool_liquidity_usd=1000.0,
                manual_live_require_sell_route=False,
                manual_live_alerts_path=str(alerts),
            )
            with self.assertRaises(ManualLiveBlockedError) as ctx:
                assert_manual_live_open_allowed(_pool(liq=500), cfg)
            self.assertEqual(ctx.exception.detail.get("rule"), "min_pool_liquidity")
            self.assertTrue(alerts.is_file())
            rows = json.loads(alerts.read_text(encoding="utf-8"))
            self.assertEqual(rows[-1]["rule"], "min_pool_liquidity")

    def test_passes_above_liquidity_without_route_check(self) -> None:
        cfg = SimpleNamespace(
            manual_live_min_pool_liquidity_usd=1000.0,
            manual_live_require_sell_route=False,
            manual_live_alerts_path="reports/manual_live_alerts.json",
        )
        out = assert_manual_live_open_allowed(_pool(liq=5000), cfg)
        self.assertTrue(out.get("ok"))

    @patch("raydium_lp1.manual_live_open.routes.check_pool_sellability")
    @patch("raydium_lp1.manual_live_open.resolve_pay_mint")
    def test_blocks_missing_alt_sell_route(self, mock_pay, mock_sell) -> None:
        from raydium_lp1.lp_pay_mint import PayMintResolution

        mock_pay.return_value = PayMintResolution(
            pay_mint="So11111111111111111111111111111111111111112",
            pay_symbol="SOL",
            pay_is_mint_a=True,
            alt_mint="MemeMint1111111111111111111111111111111111",
            alt_symbol="MEME",
        )
        sell = unittest.mock.MagicMock()
        sell.ok = False
        sell.reasons = ["no route"]
        sell.token_a.ok = True
        sell.token_b.ok = False
        sell.to_dict.return_value = {"ok": False}
        mock_sell.return_value = sell

        with tempfile.TemporaryDirectory() as tmp:
            alerts = Path(tmp) / "alerts.json"
            cfg = SimpleNamespace(
                manual_live_min_pool_liquidity_usd=100.0,
                manual_live_require_sell_route=True,
                manual_live_max_route_price_impact_pct=0,
                max_route_price_impact_pct=5.0,
                allowed_quote_symbols=("SOL", "USDC"),
                route_sources=("jupiter",),
                manual_live_alerts_path=str(alerts),
            )
            with self.assertRaises(ManualLiveBlockedError) as ctx:
                assert_manual_live_open_allowed(_pool(liq=5000), cfg)
            self.assertEqual(ctx.exception.detail.get("rule"), "sell_route")

    def test_notify_appends_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            cfg = SimpleNamespace(manual_live_alerts_path=str(path))
            notify_manual_live_blocked("test reason", _pool(), config=cfg)
            notify_manual_live_blocked("second", _pool(), config=cfg)
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["reason"], "second")


if __name__ == "__main__":
    unittest.main()
