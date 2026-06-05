"""Rent / escrow pre-trade guard."""

from __future__ import annotations

import unittest

from raydium_lp1.fee_guard import FeeGuardBlockedError
from raydium_lp1.lp_rent_escrow import assert_rent_escrow_allowed, estimate_open_rent_escrow
from raydium_lp1.lp_full_range import open_kwargs_for_wide_band


class RentEscrowTests(unittest.TestCase):
    def test_raydium_model_wide_band_low_sunk(self) -> None:
        deposit_sol = 3.0 / 180.0
        est = estimate_open_rent_escrow(
            deposit_sol=deposit_sol,
            open_kwargs=open_kwargs_for_wide_band(width_pct=80),
            settings={"sol_price_usd": 180, "max_rent_escrow_pct_of_deposit": 10},
        )
        self.assertEqual(est.rent_model, "raydium")
        self.assertLess(est.sunk_sol_est, 0.01)
        self.assertGreater(est.recoverable_sol_est, 0.005)
        assert_rent_escrow_allowed(
            deposit_sol=deposit_sol,
            open_kwargs=open_kwargs_for_wide_band(width_pct=80),
            settings={"sol_price_usd": 180, "max_rent_escrow_pct_of_deposit": 10},
        )

    def test_literal_pool_blocked(self) -> None:
        with self.assertRaises(FeeGuardBlockedError):
            assert_rent_escrow_allowed(
                deposit_sol=3.5 / 180,
                open_kwargs={"literal_pool_full_range": True, "full_range": True},
                settings={"max_rent_escrow_pct_of_deposit": 10, "sol_price_usd": 180},
            )

    def test_tiny_deposit_wide_band_allowed_raydium(self) -> None:
        assert_rent_escrow_allowed(
            deposit_sol=0.5 / 180,
            open_kwargs=open_kwargs_for_wide_band(),
            settings={"max_rent_escrow_pct_of_deposit": 10, "sol_price_usd": 180},
        )


if __name__ == "__main__":
    unittest.main()
