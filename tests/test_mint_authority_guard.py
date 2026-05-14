import unittest

from raydium_lp1.honeypot_guard import MintInspection, TOKEN_2022_PROGRAM_ID, parse_mint_data
from raydium_lp1.mint_authority_guard import (
    MintAuthorityGuardConfig,
    evaluate_mint_authority_guard,
)


def _inspection(**overrides) -> MintInspection:
    defaults = {
        "mint_address": "MINTaaa",
        "owner_program": TOKEN_2022_PROGRAM_ID,
        "freeze_authority_set": False,
        "mint_authority_set": False,
        "transfer_fee_basis_points": None,
        "has_transfer_hook": False,
        "has_permanent_delegate": False,
        "decimals": 9,
        "raw_data_length": 200,
    }
    defaults.update(overrides)
    return MintInspection(**defaults)


class MintAuthorityParserTests(unittest.TestCase):
    def test_some_mint_authority_set(self):
        data = bytearray(82)
        data[0:4] = (1).to_bytes(4, "little")
        parsed = parse_mint_data(bytes(data))
        self.assertTrue(parsed["mint_authority_set"])

    def test_none_mint_authority_clear(self):
        data = bytearray(82)
        data[0:4] = (0).to_bytes(4, "little")
        parsed = parse_mint_data(bytes(data))
        self.assertFalse(parsed["mint_authority_set"])


class MintAuthorityGuardTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        ok, reason = evaluate_mint_authority_guard(
            None, MintAuthorityGuardConfig(enabled=False), has_rpc_configured=False
        )
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_no_rpc_fails_closed_by_default(self):
        ok, reason = evaluate_mint_authority_guard(
            None, MintAuthorityGuardConfig(), has_rpc_configured=False
        )
        self.assertFalse(ok)
        self.assertIn("no Solana RPC", reason)

    def test_no_rpc_fail_open(self):
        ok, _ = evaluate_mint_authority_guard(
            None,
            MintAuthorityGuardConfig(fail_open_when_no_rpc=True),
            has_rpc_configured=False,
        )
        self.assertTrue(ok)

    def test_clean_mint_passes(self):
        ok, _ = evaluate_mint_authority_guard(
            _inspection(mint_authority_set=False),
            MintAuthorityGuardConfig(),
            has_rpc_configured=True,
        )
        self.assertTrue(ok)

    def test_live_mint_authority_rejected(self):
        ok, reason = evaluate_mint_authority_guard(
            _inspection(mint_authority_set=True),
            MintAuthorityGuardConfig(),
            has_rpc_configured=True,
        )
        self.assertFalse(ok)
        self.assertIn("mint_authority", reason)

    def test_live_mint_authority_whitelisted(self):
        inspection = _inspection(mint_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", mint_authority_set=True)
        ok, _ = evaluate_mint_authority_guard(
            inspection, MintAuthorityGuardConfig(), has_rpc_configured=True
        )
        self.assertTrue(ok)

    def test_inspection_missing_with_rpc_fails_closed(self):
        ok, reason = evaluate_mint_authority_guard(
            None, MintAuthorityGuardConfig(), has_rpc_configured=True
        )
        self.assertFalse(ok)
        self.assertIn("all configured RPCs failed", reason)


if __name__ == "__main__":
    unittest.main()
