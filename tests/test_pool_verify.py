"""Tests for Raydium pool on-chain / API verification."""

import unittest
from unittest.mock import patch

from raydium_lp1 import pool_verify


CPMM_POOL = {
    "id": "CnvFdTV9cLxxsS33cBxWD75iRvHLmPTUi3cHpwTuSAae",
    "program_id": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    "mint_a_symbol": "SOL",
    "mint_b_symbol": "MUSHU",
}

CLMM_POOL = {
    "id": "EH7e6CxAWsvvqykDevsm8fJ9URz4sUET6rMwibfuSVcc",
    "program_id": "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "mint_a_symbol": "SIREN",
    "mint_b_symbol": "USDC",
}

# User-reported "wallet" — live mainnet: Raydium CPMM dust pool (~$0.01 TVL).
DUST_CPMM_POOL = {
    "id": "HPaFuQ8m3BTLGGGwX59JuyLPdQ1aWuXs3KJKk7mivDKC",
    "program_id": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    "mint_a_symbol": "SOL",
    "mint_b_symbol": "SITCOM",
    "liquidity_usd": 0.01,
}

FAKE_WALLET = {
    "id": "7G3w8f9FakeWallet1111111111111111111111111111",
    "program_id": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
}


class ApiProgramTests(unittest.TestCase):
    def test_cpmm_pool_program_accepted(self):
        ok, reasons, label = pool_verify.verify_api_program(CPMM_POOL)
        self.assertTrue(ok, reasons)
        self.assertEqual(label, "CPMM")

    def test_clmm_pool_program_accepted(self):
        ok, _, label = pool_verify.verify_api_program(CLMM_POOL)
        self.assertTrue(ok)
        self.assertEqual(label, "CLMM")

    def test_unknown_program_rejected(self):
        bad = {**CPMM_POOL, "program_id": "11111111111111111111111111111111"}
        ok, reasons, _ = pool_verify.verify_api_program(bad)
        self.assertFalse(ok)
        self.assertTrue(any("not a known Raydium" in r for r in reasons))


class OnChainTests(unittest.TestCase):
    def test_cpmm_owner_matches(self):
        owner_cache: dict[str, str | None] = {}
        with patch.object(
            pool_verify,
            "get_account_owner",
            return_value="CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
        ):
            ok, owner, reasons = pool_verify.verify_on_chain_owner(
                CPMM_POOL["id"],
                CPMM_POOL["program_id"],
                ["https://rpc.example"],
                owner_cache=owner_cache,
            )
        self.assertTrue(ok, reasons)
        self.assertEqual(owner, CPMM_POOL["program_id"])

    def test_system_owner_rejected_as_wallet(self):
        with patch.object(
            pool_verify,
            "get_account_owner",
            return_value="11111111111111111111111111111111",
        ):
            ok, _, reasons = pool_verify.verify_on_chain_owner(
                FAKE_WALLET["id"],
                FAKE_WALLET["program_id"],
                ["https://rpc.example"],
            )
        self.assertFalse(ok)
        self.assertTrue(any("wallet" in r.lower() or "system" in r.lower() for r in reasons))

    def test_owner_mismatch_rejected(self):
        with patch.object(
            pool_verify,
            "get_account_owner",
            return_value="CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
        ):
            ok, _, reasons = pool_verify.verify_on_chain_owner(
                CPMM_POOL["id"],
                CPMM_POOL["program_id"],
                ["https://rpc.example"],
            )
        self.assertFalse(ok)
        self.assertTrue(any("owner" in r for r in reasons))


class ValidatePoolTests(unittest.TestCase):
    def test_user_reported_addresses_verify_with_mocked_chain(self):
        """Regression: addresses user called 'wallets' are Raydium pool state accounts."""

        def fake_owner(pubkey: str, *_args: object, **_kwargs: object) -> str:
            if pubkey == CPMM_POOL["id"]:
                return CPMM_POOL["program_id"]
            if pubkey == CLMM_POOL["id"]:
                return CLMM_POOL["program_id"]
            if pubkey == DUST_CPMM_POOL["id"]:
                return DUST_CPMM_POOL["program_id"]
            return "11111111111111111111111111111111"

        with patch.object(pool_verify, "get_account_owner", side_effect=fake_owner):
            for pool in (CPMM_POOL, CLMM_POOL, DUST_CPMM_POOL):
                v = pool_verify.validate_pool(
                    pool,
                    api_base="https://api-v3.raydium.io",
                    rpc_urls=["https://rpc.example"],
                    verify_on_chain=True,
                )
                self.assertTrue(v.ok, v.reasons)
                self.assertIn("chain", v.proof_tag)

    def test_validate_full_failure_when_no_account(self):
        with patch.object(pool_verify, "get_account_owner", return_value=None):
            v = pool_verify.validate_pool(
                CPMM_POOL,
                api_base="https://api-v3.raydium.io",
                rpc_urls=["https://rpc.example"],
                verify_on_chain=True,
            )
        self.assertFalse(v.ok)
        self.assertTrue(any("no account" in r for r in v.reasons))


class RaydiumApiRoundTripTests(unittest.TestCase):
    def test_fetch_by_id_parses_success(self):
        payload = {
            "success": True,
            "data": [{"id": CPMM_POOL["id"], "type": "Standard"}],
        }

        def fake_fetch(_url: str, _timeout: int) -> dict:
            return payload

        row = pool_verify.fetch_raydium_pool_by_id(
            CPMM_POOL["id"],
            api_base="https://api-v3.raydium.io",
            fetch_json=fake_fetch,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], CPMM_POOL["id"])


if __name__ == "__main__":
    unittest.main()
