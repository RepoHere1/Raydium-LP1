import unittest

from raydium_lp1.lp_position_economics import build_open_cost_summary, enrich_position_row


class LpPositionEconomicsTests(unittest.TestCase):
    def test_break_even_from_rent_and_fees(self) -> None:
        row = {
            "pair": "SOL/MEME",
            "liquidity_usd": 10_000.0,
            "fee_24h_usd": 100.0,
            "input_pay_symbol": "USDC",
            "input_amount_human": 10.0,
            "spend_less_get_more": {
                "effective_deposit_usd": 10.0,
                "rent_escrow": {
                    "sunk_usd": 1.94,
                    "recoverable_sol_est": 0.0075,
                    "sol_price_usd": 180.0,
                },
            },
            "spend_less_cost_analysis": {
                "total_network_fee_sol": 0.00002,
                "rent_escrow_estimate": {"sunk_usd": 1.94, "recoverable_sol_est": 0.0075, "sol_price_usd": 180},
            },
        }
        s = build_open_cost_summary(row, sol_price_usd=180.0, failed_attempts_usd=0.5)
        self.assertAlmostEqual(s["break_even_fee_income_usd"], 1.94 + 0.5 + 0.00002 * 180, places=2)
        self.assertAlmostEqual(s["break_even_pct_of_deposit"], 24.4, places=0)
        self.assertIsNotNone(s["days_to_breakeven_at_current_fee_rate"])

    def test_enrich_attaches_block(self) -> None:
        row = enrich_position_row({"input_amount_human": 5, "lp_pay_symbol": "USDC"})
        self.assertIn("open_economics", row)
        self.assertEqual(row["open_economics"]["deposit_usd"], 5.0)


if __name__ == "__main__":
    unittest.main()
