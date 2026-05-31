import unittest
from unittest.mock import patch

from raydium_lp1.super_brainiac.possibilities import (
    BrainiacConfig,
    classify_pay_alt_pair,
    fee_rate_as_percent,
    fee_tier_boost,
    in_range_factor,
    pool_passes_universe,
    score_strategy_for_pool,
)


class SuperBrainiacTests(unittest.TestCase):
    def _pool(self) -> dict:
        return {
            "id": "PoolX",
            "program_id": "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
            "mint_a_symbol": "SOL",
            "mint_b_symbol": "MEME",
            "mint_a": "So11111111111111111111111111111111111111112",
            "mint_b": "MemeMint1111111111111111111111111111111111",
            "liquidity_usd": 8000.0,
            "volume_24h_usd": 40000.0,
            "fee_24h_usd": 120.0,
            "fee_rate": 0.01,
            "open_time": 1_700_000_000,
            "raw": {
                "day": {"priceMin": 0.9, "priceMax": 1.1, "volumeFee": 120},
            },
        }

    def test_classify_rejects_double_pay(self) -> None:
        bad = classify_pay_alt_pair(
            {"mint_a_symbol": "SOL", "mint_b_symbol": "USDC"},
            allowed_pay=frozenset({"SOL", "USDC", "USDT"}),
        )
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["pair_shape"], "pay/pay")

    def test_classify_accepts_pay_alt(self) -> None:
        ok = classify_pay_alt_pair(
            {"mint_a_symbol": "SOL", "mint_b_symbol": "MEME"},
            allowed_pay=frozenset({"SOL", "USDC", "USDT"}),
        )
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["pair_label"], "SOL/MEME")

    def test_universe_blocks_sol_usdc(self) -> None:
        pool = self._pool()
        pool["mint_a_symbol"] = "SOL"
        pool["mint_b_symbol"] = "USDC"
        cfg = BrainiacConfig(require_pay_alt_pair_only=True, min_liquidity_usd=100)
        scanner = unittest.mock.MagicMock(
            allowed_quote_symbols=("SOL", "USDC"),
            route_sources=("jupiter",),
            lp_open_pay_token_only=True,
        )
        ok, reasons = pool_passes_universe(pool, cfg, scanner)
        self.assertFalse(ok)
        self.assertTrue(any("double-pay" in r for r in reasons))

    def test_fee_rate_percent(self) -> None:
        self.assertAlmostEqual(fee_rate_as_percent({"fee_rate": 0.04}), 4.0)

    def test_fee_tier_boost_prefers_one_to_four(self) -> None:
        cfg = BrainiacConfig()
        self.assertGreater(fee_tier_boost(2.0, cfg), fee_tier_boost(0.05, cfg))

    def test_in_range_full_range_high(self) -> None:
        ir = in_range_factor(self._pool(), width_pct=100, placement="full_range", skew=0)
        self.assertEqual(ir, 1.0)

    @patch("raydium_lp1.super_brainiac.possibilities.resolve_pay_mint")
    @patch("raydium_lp1.super_brainiac.possibilities.check_pool_buy_routes")
    @patch("raydium_lp1.super_brainiac.possibilities.routes.check_pool_sellability")
    def test_score_strategy_positive(self, mock_sell, mock_buy, mock_pay) -> None:
        from raydium_lp1.lp_pay_mint import PayMintResolution

        mock_pay.return_value = PayMintResolution(
            pay_mint="So11111111111111111111111111111111111111112",
            pay_symbol="SOL",
            pay_is_mint_a=True,
            alt_mint="MemeMint1111111111111111111111111111111111",
            alt_symbol="MEME",
        )
        mock_buy.return_value = (True, [])
        sell = unittest.mock.MagicMock()
        sell.ok = True
        sell.reasons = []
        mock_sell.return_value = sell

        cfg = BrainiacConfig(deposit_usd=3.0)
        row = score_strategy_for_pool(
            self._pool(),
            "centered_tight_range",
            cfg=cfg,
            scanner=unittest.mock.MagicMock(
                lp_default_range_width_pct=15,
                lp_skew_use_momentum=True,
                allowed_quote_symbols=("SOL", "USDC"),
            ),
        )
        self.assertGreater(row["brainiac_score"], 0)
        self.assertGreater(row["theoretical_apr_pct"], 0)


if __name__ == "__main__":
    unittest.main()
