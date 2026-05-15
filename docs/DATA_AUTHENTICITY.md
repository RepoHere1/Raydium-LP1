# Data authenticity audit (Raydium-LP1)

This document lists **what is live** vs **modeled/stub** in `src/raydium_lp1/`.  
Each scan also writes `reports/data_provenance.json` with endpoints and settings used.

## Live (fetched from the network at scan time)

| Module | Data | Source |
|--------|------|--------|
| `scanner.py` | Pool list (APR, TVL, volume, mints, `id`, `programId`) | `GET https://api-v3.raydium.io/pools/info/list` |
| `pool_verify.py` | Pool state account proof | Solana RPC `getMultipleAccounts` / `getAccountInfo` (owner must be CPMM/CLMM/AMM) |
| `pool_verify.py` | Optional per-pool confirm | `GET https://api-v3.raydium.io/pools/info/ids?ids=<POOL_STATE>` |
| `routes.py` | Sell-route probes | `https://quote-api.jup.ag/v6/quote`, Raydium swap compute API |
| `robust_routes.py` | Extra quotes | Orca swap-quote API, Raydium AMM compute (5m cache) |
| `wallet.py` | SOL balance | Your configured Solana RPC `getBalance` |

**Important:** Solana **pool state accounts** use the same base58 shape as wallets. Explorers often say “wallet” for any pubkey. Use the **PROOF** column (`CPMM+chain`, `CLMM+chain`) — that means RPC proved the account is owned by a Raydium pool program.

## Not live / not real trades (by design)

| Module | What | Location |
|--------|------|----------|
| `scanner.py` | No signed swaps; `dry_run` enforced | `main()`, `ScannerConfig.dry_run` |
| `emergency.py` | Emergency “swap” plans are dry-run only | `plan_emergency_close()` — `position_token_amount=1_000_000` placeholder (~line 178) |
| `emergency.py` | Alerts never execute on-chain | `action="would_swap_to_base"`, `dry_run=True` |
| `dial_in_analyst.py` | Settings suggestions from rejection stats | Not a market oracle |
| `networks.py` | Ethereum / Base adapters | Stub only — `supports_live=False` |
| `wallet.py` | `sell_all_to_base` | Plan JSON only when `dry_run=True` |

## Tests (not used in production scans)

| Location | Purpose |
|----------|---------|
| `tests/*.py` | Mock Raydium/Jupiter/RPC responses; fake pool ids like `pool-1` |
| `tests/scan_test_defaults.py` | Disables on-chain verify for unit tests |

## Example: `HPaFuQ8m3BTLGGGwX59JuyLPdQ1aWuXs3KJKk7mivDKC`

Live checks (mainnet):

- Raydium API: **Standard** SOL / $SITCOM pool, `programId` = CPMM.
- On-chain **owner** = `CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C` (Raydium CPMM program).

That is a **real Raydium pool state account**, not a fabricated id. It often has **~$0.01 TVL** and extreme APR — the scanner should **reject** it on `min_liquidity_usd`, not because the address is fake.

Verify yourself:

```text
https://api-v3.raydium.io/pools/info/ids?ids=HPaFuQ8m3BTLGGGwX59JuyLPdQ1aWuXs3KJKk7mivDKC
```
