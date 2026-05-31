"""Rent / escrow pre-trade guard."""

from __future__ import annotations

import unittest

from raydium_lp1.fee_guard import FeeGuardBlockedError
from raydium_lp1.lp_rent_escrow import assert_rent_escrow_allowed, estimate_open_rent_escrow
from raydium_lp1.lp_full_range import open_kwargs_for_wide_band


class RentEscrowTests(unittest.TestCase):
    def test_wide_band_within_cap(self) -> None:
        # ~$100 deposit: wide-band sunk ~$7 at 180 SOL/USD stays under 10% cap
        deposit_sol = 100.0 / 180.0
        est = estimate_open_rent_escrow(
            deposit_sol=deposit_sol,
            open_kwargs=open_kwargs_for_wide_band(width_pct=80),
            settings={"sol_price_usd": 180, "max_rent_escrow_pct_of_deposit": 10},
        )
        self.assertLess(est.sunk_pct_of_deposit, 10.0)
        self.assertFalse(est.literal_pool_ticks)
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

    def test_tiny_deposit_wide_band_blocked(self) -> None:
        with self.assertRaises(FeeGuardBlockedError):
            assert_rent_escrow_allowed(
                deposit_sol=0.5 / 180,
                open_kwargs=open_kwargs_for_wide_band(),
                settings={"max_rent_escrow_pct_of_deposit": 10, "sol_price_usd": 180},
            )


if __name__ == "__main__":
    unittest.main()
