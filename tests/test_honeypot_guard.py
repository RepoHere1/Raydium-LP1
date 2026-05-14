import unittest

from raydium_lp1.honeypot_guard import (
    EXT_PERMANENT_DELEGATE,
    EXT_TRANSFER_FEE_CONFIG,
    EXT_TRANSFER_HOOK,
    HoneypotGuardConfig,
    MintInspection,
    TOKEN_2022_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    evaluate_honeypot_guard,
    evaluate_inspection,
    parse_mint_data,
)


def make_classic_mint(freeze_authority_set: bool = False) -> bytes:
    """Build the 82-byte legacy SPL mint layout (no Token-2022 extensions)."""
    data = bytearray(82)
    data[0:4] = (1).to_bytes(4, "little")
    data[4:36] = b"\x11" * 32
    data[36:44] = (1_000_000).to_bytes(8, "little")
    data[44] = 9
    data[45] = 1
    data[46:50] = (1 if freeze_authority_set else 0).to_bytes(4, "little")
    if freeze_authority_set:
        data[50:82] = b"\x22" * 32
    return bytes(data)


def make_token_2022_mint(
    transfer_fee_basis_points: int | None = None,
    has_transfer_hook: bool = False,
    has_permanent_delegate: bool = False,
    freeze_authority_set: bool = False,
) -> bytes:
    """Build a Token-2022 mint with optional extensions for testing."""

    base = make_classic_mint(freeze_authority_set=freeze_authority_set)
    # 83 bytes of padding to reach byte 165, then 1 byte account_type, then TLV.
    header = bytearray(base) + bytearray(83) + bytearray([1])
    tlv = bytearray()

    def add_ext(ext_type: int, payload: bytes) -> None:
        tlv.extend(ext_type.to_bytes(2, "little"))
        tlv.extend(len(payload).to_bytes(2, "little"))
        tlv.extend(payload)

    if transfer_fee_basis_points is not None:
        fee = bytearray(108)
        fee[64:72] = (0).to_bytes(8, "little")
        fee[72:80] = (0).to_bytes(8, "little")
        fee[80:88] = (0).to_bytes(8, "little")
        fee[88:90] = (0).to_bytes(2, "little")
        fee[90:98] = (1).to_bytes(8, "little")
        fee[98:106] = (0).to_bytes(8, "little")
        fee[106:108] = int(transfer_fee_basis_points).to_bytes(2, "little")
        add_ext(EXT_TRANSFER_FEE_CONFIG, bytes(fee))
    if has_transfer_hook:
        add_ext(EXT_TRANSFER_HOOK, b"\x00" * 64)
    if has_permanent_delegate:
        add_ext(EXT_PERMANENT_DELEGATE, b"\x00" * 32)

    return bytes(header + tlv)


class ParserTests(unittest.TestCase):
    def test_classic_mint_no_extensions(self):
        parsed = parse_mint_data(make_classic_mint(freeze_authority_set=False))
        self.assertFalse(parsed["freeze_authority_set"])
        self.assertIsNone(parsed["transfer_fee_basis_points"])
        self.assertFalse(parsed["has_transfer_hook"])
        self.assertFalse(parsed["has_permanent_delegate"])

    def test_classic_mint_with_freeze_authority(self):
        parsed = parse_mint_data(make_classic_mint(freeze_authority_set=True))
        self.assertTrue(parsed["freeze_authority_set"])

    def test_token_2022_transfer_fee_50_percent(self):
        # 5000 basis points = 50%
        parsed = parse_mint_data(make_token_2022_mint(transfer_fee_basis_points=5000))
        self.assertEqual(parsed["transfer_fee_basis_points"], 5000)
        self.assertIn(EXT_TRANSFER_FEE_CONFIG, parsed["extensions_seen"])

    def test_token_2022_with_transfer_hook_and_permanent_delegate(self):
        parsed = parse_mint_data(
            make_token_2022_mint(has_transfer_hook=True, has_permanent_delegate=True)
        )
        self.assertTrue(parsed["has_transfer_hook"])
        self.assertTrue(parsed["has_permanent_delegate"])

    def test_truncated_data_does_not_crash(self):
        parsed = parse_mint_data(b"")
        self.assertFalse(parsed["freeze_authority_set"])
        parsed = parse_mint_data(b"\x00" * 40)
        self.assertFalse(parsed["freeze_authority_set"])


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


class EvaluateInspectionTests(unittest.TestCase):
    def test_clean_mint_passes(self):
        ok, reason = evaluate_inspection(_inspection(), HoneypotGuardConfig())
        self.assertTrue(ok, msg=reason)

    def test_high_sell_tax_rejected(self):
        ok, reason = evaluate_inspection(
            _inspection(transfer_fee_basis_points=3500),
            HoneypotGuardConfig(max_sell_tax_percent=30.0),
        )
        self.assertFalse(ok)
        self.assertIn("on-chain sell tax", reason)

    def test_sell_tax_at_or_below_limit_passes(self):
        ok, _ = evaluate_inspection(
            _inspection(transfer_fee_basis_points=3000),
            HoneypotGuardConfig(max_sell_tax_percent=30.0),
        )
        self.assertTrue(ok)

    def test_freeze_authority_rejected_by_default(self):
        ok, reason = evaluate_inspection(
            _inspection(freeze_authority_set=True),
            HoneypotGuardConfig(),
        )
        self.assertFalse(ok)
        self.assertIn("freeze authority", reason)

    def test_freeze_authority_whitelisted_passes(self):
        config = HoneypotGuardConfig(
            allowed_freeze_authority_mints=frozenset({"USDCmint"}),
        )
        ok, _ = evaluate_inspection(
            _inspection(mint_address="USDCmint", freeze_authority_set=True),
            config,
        )
        self.assertTrue(ok)

    def test_transfer_hook_rejected(self):
        ok, reason = evaluate_inspection(
            _inspection(has_transfer_hook=True),
            HoneypotGuardConfig(),
        )
        self.assertFalse(ok)
        self.assertIn("TransferHook", reason)

    def test_permanent_delegate_rejected(self):
        ok, reason = evaluate_inspection(
            _inspection(has_permanent_delegate=True),
            HoneypotGuardConfig(),
        )
        self.assertFalse(ok)
        self.assertIn("PermanentDelegate", reason)


class EvaluateHoneypotGuardTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        ok, reason, inspection = evaluate_honeypot_guard("M", HoneypotGuardConfig(enabled=False), [])
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertIsNone(inspection)

    def test_no_rpc_and_fail_closed_rejects(self):
        ok, reason, _ = evaluate_honeypot_guard("M", HoneypotGuardConfig(), rpc_urls=[])
        self.assertFalse(ok)
        self.assertIn("no Solana RPC", reason)

    def test_no_rpc_and_fail_open_passes(self):
        ok, reason, _ = evaluate_honeypot_guard(
            "M",
            HoneypotGuardConfig(fail_open_when_no_rpc=True),
            rpc_urls=[],
        )
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_cache_hit_does_not_hit_rpc(self):
        cache = {"MINTaaa": _inspection(transfer_fee_basis_points=5000)}
        config = HoneypotGuardConfig(max_sell_tax_percent=30.0)
        ok, reason, inspection = evaluate_honeypot_guard(
            "MINTaaa", config, rpc_urls=["http://does-not-exist.invalid"], cache=cache
        )
        self.assertFalse(ok)
        self.assertIn("on-chain sell tax", reason)
        self.assertEqual(inspection.transfer_fee_basis_points, 5000)


if __name__ == "__main__":
    unittest.main()
