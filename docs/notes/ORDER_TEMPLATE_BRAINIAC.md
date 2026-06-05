# Brainiac No Escrow Skewed — LIVE order notes (full procedure)

Copy **“Paste to Cursor”** or **“Paste to your notes”** below. Replace `POOL_ID_HERE` and `DEPOSIT_USD_HERE`.

---

## Paste to your notes / Cursor

```
Brainiac No Escrow Skewed — Raydium-LP1 LIVE

Strategy ID: brainiac_cursor_success_80_skewed_no_escrow
Display: BRAINIAC-CURSOR-SUCCESS-80%-SKEWED-WIDE-No ESCROW

Pool ID: POOL_ID_HERE
Deposit USD: DEPOSIT_USD_HERE   # e.g. 1.00

=== 1) Settings (required) ===
config/settings.json must have:
  lp_active_strategy = brainiac_cursor_success_80_skewed_no_escrow
  mode = live
  dry_run = false
  lp_sweep_junk_to_pay_leg = true

Apply via wizard (Python patch, backs up settings) OR:
  cd C:\Users\Taylor\Raydium-LP1
  .\scripts\set_brainiac_strategy.ps1

Signer: secrets/lp1_signer.json (or env), RPC in .env, mode_toggle must read live (UTF-8 BOM-safe).

=== 2) How to run (preferred) ===
  cd C:\Users\Taylor\Raydium-LP1
  .\brainiac_wizard.cmd

Wizard defaults (config/brainiac_wizard_last.json):
  use_auto_live_policy = yes     → coded SUPER-BRAINIAC after pool entered
  skip_fund_swap = yes           → when deposit ≤ $2.50 (micro opens)
  fund_non_pay_fraction = 0.35   → if funding and deposit < $3
  wide_width_pct = 80
  min_in_range_factor = 0.55
  reset_fee_session = no         → unless fee-guard blocked you earlier
  run_pretrade = yes
  apply_brainiac_strategy = yes
  sol_price_usd = 0              → use settings ~180; NEVER type 80 (that is width %)

Preview first: Preview only = y → skew, pay/alt, SPEND LESS, issues.
LIVE: Preview only = n → type LIVE at confirm.

One-liner (saved defaults + auto policy, still asks LIVE confirm):
  .\brainiac_wizard.cmd -PoolId "POOL_ID_HERE" -DepositUsd DEPOSIT_USD_HERE -Yes

Fully automatic LIVE (prompts pool id only; optional -PoolId to skip):
  .\brainiac_wizard.cmd -Live -DepositUsd DEPOSIT_USD_HERE
  .\brainiac_wizard.cmd -Live -PoolId "POOL_ID_HERE" -DepositUsd DEPOSIT_USD_HERE

Core code:
  src/raydium_lp1/lp_brainiac_cursor_success.py   — order type + skew grid + auto policy
  src/raydium_lp1/brainiac_open_runner.py         — pretrade, fund, open, report
  scripts/brainiac_open_wizard.py                 — interactive wizard

=== 3) What the procedure does (in order) ===
A. Pre-trade (scripts/_brainiac_pretrade_analysis.py)
   - Resolve pay-type vs non-pay (SOL/USDC/USDT = pay; other mint = alt)
   - Pool TVL, fee APR, in-range factor at best skew
   - Wallet SOL/USDC headroom, SPEND LESS clamp, fee-session budget
   - Block if min_in_range_factor set and model overlap too low

B. SUPER-BRAINIAC placement (80% total width, not full-range)
   - 24h price min/max band → grid skew -1..+1 (41 steps)
   - Pick skew with highest in_range_factor (fee overlap vs chop)
   - Example skew -1.0 → ~60% below spot / ~20% above (asymmetric straddle)
   - Score vs other strategies; leader APR is model-only, not a promise

C. Fee guard + SPEND LESS (per open)
   - fee_guard_enabled, Raydium rent model (recoverable NFT; no fake 0.072 tick-array)
   - Session cap ~0.4 SOL / 24 attempts; priority fee capped
   - No auto fallback to pay-only wide band on failure

D. Funding (optional)
   - If skip_fund_swap: no Jupiter tx (you already hold alt leg — saves fee + slippage)
   - Else: swap pay-type → non-pay for fund_non_pay_fraction × deposit (35–42%)
   - Never fund from non-pay mint; never sweep junk into non-pay

E. Pay-type top-up if needed (USDC pools)
   - If short USDC for inventory open, may swap SOL→USDC (pay-type only path)

F. CLMM open (open_clmm_with_brainiac_cursor_success → open_clmm_candidate)
   - Style: two-sided wallet_inventory, Brainiac 80% skewed ticks
   - pay_mint_only = false (no pay-only wide fallback)
   - band_tick_steps capped on micro deposits (<$2 → 18 steps, <$3 → 24)
   - Sign open_position via Node raydium_clmm; manual_live + pool verification

G. Post-open settlement (unless skip_settle_after)
   - Sweep stray SPL from pair → pay-type (lp_junk_to_pay / settle_wallet_after_brainiac)
   - Native SOL stays for fees when pay-type is USDC

=== 4) Pool / wallet requirements ===
- Pool must include a pay-type leg (allowed_quote_symbols / resolve_pay_mint).
- Keep ≥ ~0.12 SOL for rent buffer + failed-tx retries (position rent recoverable on close).
- $1 two-sided on thin memecoin pools: high Raydium Custom:6017 risk — prefer skip fund + existing alt, or $2–3+.

=== 5) End report (must deliver) ===
After LIVE, report saved: reports/brainiac_wizard_last_report.json

Include:
  - pay_type_symbol / non_pay_symbol
  - placement: skew, tick_lower_pct_below, tick_upper_pct_above, in_range_factor
  - fund_non_pay: skipped or swap sig
  - open: tx signature, position NFT mint, clmm error if any
  - wallet_settlement: junk→pay sweep result
  - permanent_loss_usd:
      network_fees_from_ledger (non-recoverable tx cost)
      wallet_delta_usd (total wallet change)
      deposit_in_lp_usd (capital in position — recoverable on close)
      interpretation line separating fees vs LP principal

=== 6) Paste block for Cursor agent ===
Open LIVE on pool POOL_ID_HERE for Deposit USD DEPOSIT_USD_HERE using
brainiac_cursor_success_80_skewed_no_escrow / brainiac_wizard or
open_clmm_with_brainiac_cursor_success with auto policy.
Find 80% skew placement with maximum 24h price overlap (not headline pool APR alone).
Style: two-sided wallet_inventory (Brainiac 80% skewed). Skip pay→non-pay fund if deposit ≤ $2.50.
Fund non-pay from pay-type only if needed and not skipped. Use USDC/SOL pay leg as resolved.
No pay-only fallback. Give full report including real USD lost to network fees vs LP deposit.
```

---

## Example ($1 open)

```
Pool ID: CXuK5H4TZgb28vuucNoJh8LXRmR4VjdEuL6pXmMenSod
Deposit USD: 1.00
```

With auto policy: skip Jupiter fund, 80% skew grid, min in-range 0.55, post-open sweep to pay-type.
