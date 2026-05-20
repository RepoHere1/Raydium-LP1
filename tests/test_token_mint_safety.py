"""Unit tests for SPL mint exit-safety (Token-2022 transfer fee + program owner)."""

import unittest

from raydium_lp1.token_mint_safety import (
    SPL_TOKEN_PROGRAM,
    TOKEN_2022_PROGRAM,
    validate_pool_mints_exit_safety,
)

WSOL = "So11111111111111111111111111111111111111112"
MEME = "MemEMintAddressGoesHere111111111111111111111"


def _pool() -> dict:
    return {
        "mint_a": WSOL,
        "mint_a_symbol": "SOL",
        "mint_b": MEME,
        "mint_b_symbol": "MEME",
    }


class TokenMintSafetyTests(unittest.TestCase):
    def test_accepts_standard_mints_without_transfer_fee_extension(self) -> None:
        payload = {
            "result": {
                "value": [
                    {
                        "owner": SPL_TOKEN_PROGRAM,
                        "data": {"parsed": {"type": "mint", "info": {"decimals": 9, "extensions": []}}},
                    },
                    {
                        "owner": SPL_TOKEN_PROGRAM,
                        "data": {"parsed": {"type": "mint", "info": {"decimals": 6}}},
                    },
                ]
            }
        }

        def rpc_post(_url: str, body: dict) -> dict:
            self.assertEqual(body.get("method"), "getMultipleAccounts")
            return payload

        ok, reasons = validate_pool_mints_exit_safety(
            _pool(),
            rpc_urls=["https://example.invalid/rpc"],
            max_transfer_fee_bps=1500,
            require_standard_token_program=True,
            rpc_post=rpc_post,
        )
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_rejects_token2022_transfer_fee_over_cap(self) -> None:
        high_fee = {
            "extension": "transferFeeConfig",
            "state": {
                "newerTransferFee": {"transferFeeBasisPoints": 2500, "maximumFee": "0"},
                "olderTransferFee": {"transferFeeBasisPoints": 0, "maximumFee": "0"},
            },
        }
        payload = {
            "result": {
                "value": [
                    {
                        "owner": SPL_TOKEN_PROGRAM,
                        "data": {"parsed": {"type": "mint", "info": {"decimals": 9}}},
                    },
                    {
                        "owner": TOKEN_2022_PROGRAM,
                        "data": {
                            "parsed": {
                                "type": "mint",
                                "info": {"decimals": 6, "extensions": [high_fee]},
                            }
                        },
                    },
                ]
            }
        }

        def rpc_post(_url: str, _body: dict) -> dict:
            return payload

        ok, reasons = validate_pool_mints_exit_safety(
            _pool(),
            rpc_urls=["https://example.invalid/rpc"],
            max_transfer_fee_bps=1500,
            require_standard_token_program=True,
            rpc_post=rpc_post,
        )
        self.assertFalse(ok)
        self.assertTrue(any("2500" in r for r in reasons))

    def test_rejects_non_spl_mint_owner(self) -> None:
        payload = {
            "result": {
                "value": [
                    {
                        "owner": SPL_TOKEN_PROGRAM,
                        "data": {"parsed": {"type": "mint", "info": {"decimals": 9}}},
                    },
                    {
                        "owner": "11111111111111111111111111111111",
                        "data": {"parsed": {"type": "mint", "info": {"decimals": 6}}},
                    },
                ]
            }
        }

        def rpc_post(_url: str, _body: dict) -> dict:
            return payload

        ok, reasons = validate_pool_mints_exit_safety(
            _pool(),
            rpc_urls=["https://example.invalid/rpc"],
            max_transfer_fee_bps=1500,
            require_standard_token_program=True,
            rpc_post=rpc_post,
        )
        self.assertFalse(ok)
        self.assertTrue(any("not SPL Token" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
