"""ScannerConfig kwargs for unit tests that use fake pool ids (not mainnet pubkeys)."""

SCAN_TEST_DISABLE_VERIFY = {
    "require_verified_raydium_pool": False,
    "verify_pool_on_chain": False,
    "verify_pool_raydium_api": False,
}

# Raydium CPMM program id — add to mocked api-v3 list payloads when tests need program_id.
RAYDIUM_CPMM_PROGRAM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
