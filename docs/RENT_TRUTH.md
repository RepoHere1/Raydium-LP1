# CLMM open costs — what Raydium actually charges vs LP1 (fixed)

## Raydium (on-chain truth)

| Item | Typical cost | Returned on close? |
|------|----------------|-------------------|
| Network fee (base + priority) | ~0.00001–0.0005 SOL | No |
| Position NFT + personal position | ~0.007–0.009 SOL | **Yes** (burn/close) |
| SPL ATA (if missing) | ~0.002 SOL | **Yes** (close ATA) |
| Tick-array accounts | **$0 on active pools** | N/A — arrays already exist |

Raydium’s SDK (`openPositionFromBase`) only adds **create tick array** instructions when that array does not exist yet. Busy pools already have arrays along the price curve, so the UI can open for “pennies” of **network fee** plus **recoverable** rent locked briefly in your wallet.

## What LP1 wrongly assumed (pre-fix)

1. **`clmm_open_rent_sol = 0.055`** — treated as burned every open; reality ~0.008 recoverable.
2. **`lp_rent_escrow` sunk model** — multiplied **0.072 SOL** by 15–55% on every band shape as “non-recoverable” tick rent.
3. **`max_rent_escrow_pct_of_deposit` (10%)** — blocked $3–10 opens using that inflated sunk number.
4. **SPEND LESS USDC rule** — required **0.14 SOL** headroom citing “0.072 SOL tick-array in one instruction” for every USDC open.
5. **Wide 80% @ $3** — blocked as needing **$70+** deposit at 10% sunk cap.

None of that matches Raydium’s default path on liquid pools.

## What LP1 does now (default `rent_model: raydium`)

- **Recoverable** ~0.0075 SOL (+ optional ATA) — same order of magnitude as Raydium UI.
- **Sunk** tick-array rent **0** unless literal pool ticks (still disabled) or you enable `lp_rent_conservative_estimates: true`.
- Rent guard blocks only when **sunk** rent is material (>0.004 SOL) **and** over `% of deposit` cap.
- Default **`clmm_open_rent_sol`** = **0.009** (recoverable headroom, not 0.055 burned).
- USDC-pay opens need **~0.02–0.03 SOL** wallet headroom, not 0.14.

## Optional: old pessimistic model

In `config/settings.json`:

```json
"lp_rent_conservative_estimates": true
```

Restores the previous high sunk estimates for manual risk-aversion only.
