"""CLMM close/burn wiring tests (no live RPC)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from raydium_lp1 import lp_order_rules


class TestLpCloseBurn(unittest.TestCase):
    def test_close_passes_ensure_burn_nft(self):
        with patch("raydium_lp1.raydium_clmm.close_position", return_value={"ok": True}) as mock:
            lp_order_rules.close_clmm_position("NFT123")
        mock.assert_called_once()
        self.assertTrue(mock.call_args.kwargs.get("ensure_burn_nft"))

    def test_burn_empty_nft_calls_script(self):
        with patch("raydium_lp1.raydium_clmm.burn_position_nft", return_value={"ok": True}) as mock:
            lp_order_rules.burn_empty_clmm_nft("NFT123")
        mock.assert_called_once_with(position_nft_mint="NFT123", priority_fee_micro_lamports=None, timeout=90.0)

    def test_burn_all_skips_nonzero_liquidity(self):
        positions = [
            {"position_nft_mint": "A", "liquidity": "0", "pool_id": "p1"},
            {"position_nft_mint": "B", "liquidity": "99", "pool_id": "p2"},
        ]
        with patch("raydium_lp1.lp_order_rules.burn_empty_clmm_nft", return_value={"ok": True}) as mock:
            out = lp_order_rules.burn_all_empty_clmm_nfts(positions=positions)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["nft"], "A")
        mock.assert_called_once_with("A", timeout=90.0)


if __name__ == "__main__":
    unittest.main()
