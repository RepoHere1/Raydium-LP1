# BRAINIAC-CURSOR-SUCCESS-80%-SKEWED-WIDE-No ESCROW — success report

**Order type ID (settings):** `brainiac_cursor_success_80_skewed_no_escrow`  
**Display name:** BRAINIAC-CURSOR-SUCCESS-80%-SKEWED-WIDE-No ESCROW  
**Code module:** `src/raydium_lp1/lp_brainiac_cursor_success.py`

---

## Synopsis (what this order type does)

1. **Scores the pool** with SUPER-BRAINIAC (fee tier, churn, 24h volume, strategy leaderboard).
2. **Fixes total band width at 80%** of spot (not literal pool min/max ticks).
3. **Grid-searches skew** (−1…+1) to maximize overlap with Raydium `day.priceMin`–`priceMax` — producing asymmetric ticks (e.g. **48% below / 32% above** on SOL/IDLE, skew −0.4).
4. **Opens a two-sided CLMM straddle** using wallet **SOL + alt** (`wallet_inventory_full_range`), **not** pay-only SOL fallback.
5. **Uses the Raydium rent model** — recoverable position NFT rent (~0.008 SOL), **$0 sunk** tick-array fiction; SPEND LESS does **not** auto-fallback to single-sided wide.

Pick it on the dashboard under **LP order entry → CLMM style**, or call `open_clmm_with_brainiac_cursor_success()` / `scripts/rebalance_sol_idle_brainiac.py`.

---

## Why this was a success

### 1. Fee placement beat naive “999% APR” entry

Raydium UI showed **>999% APR** on SOL/IDLE `CXuK5H4TZgb28vuucNoJh8LXRmR4VjdEuL6pXmMenSod`. That number is a **liquidity-share fantasy** at tiny deposit/TVL, not a guarantee.

Brainiac compared order shapes on the same pool:

| Strategy (model) | Placement | Width | Brainiac score (rel.) |
|------------------|-----------|-------|------------------------|
| volatility_atr_width | centered | 55% | **Highest** |
| standard_full_range | wide centered | 80% | **Lowest** among wides |

**Lesson:** For this pool, **skewed 80% aligned to the 24h range** beat **centered 80%** for expected in-range fee capture. We did **not** jump in on headline APR alone.

### 2. Two-sided straddle actually landed on-chain

Earlier rebalance attempts used `force_pay_token_only=True` and fell back to **single-sided SOL** (`wide_pay_only_single_side_fallback`), which is weaker for fee capture when the alt leg (IDLE) is required.

This procedure used:

- `force_pay_token_only=False`
- `wallet_inventory_full_range=True`
- Pre-fund **IDLE** via one cost-effective SOL→IDLE swap when the wallet was short the alt leg

**Result:** Confirmed two-sided opens with `pay_mint_only: false`, `wide_range: false`, real `other_amount_max` on IDLE leg.

### 3. “No ESCROW” — economic success, not marketing

**Permanent USD loss** for the full close-all + reopen procedure was about **$0.01–0.02** in **network fees** only.

- **Sunk tick-array rent:** **$0.00** (Raydium model; active pool arrays already exist).
- **Recoverable NFT rent:** ~**$1.35 per position** — returns on close/burn, **not** burned principal.
- **~$33+ in LP deposits** left the wallet but remain **in the pools** (recoverable ± IL/fees).

The old LP1 fiction (~0.072 SOL “sunk” per open) would have **blocked** or **panicked** the user out of valid Raydium opens. This order type is wired to **`lp_rent_conservative_estimates: false`** and **no wide→single-sided SPEND LESS fallback**.

### 4. Operational checklist passed

| Step | Outcome |
|------|---------|
| Close all 6 legacy positions | ✓ (IDLE preserved, no trash-sweep on close) |
| Brainiac skew grid | ✓ skew −0.4, IR factor ~0.94 |
| Equal-split budget math | ✓ ~$14.74 × 4 target (3 opens completed; 4th blocked on SOL headroom) |
| USD cost report | ✓ `reports/sol_idle_brainiac_procedure.json` |
| Ghost NFT cleanup | ✓ burns on failed txs |

### 5. What limited “4 of 4”

Not strategy failure — **wallet SOL headroom** after two full-size straddles + IDLE funding swap. Session fee-guard cap (5 txs) also blocked opens 3–4 until ledger reset; later opens needed smaller size or more SOL.

---

## How to use the new order type

### Dashboard

1. Open **LP order entry — CLMM style**.
2. Select card **BRAINIAC-CURSOR-SUCCESS-80%-SKEWED-WIDE-No ESCROW**.
3. **Save settings** (`lp_active_strategy` = `brainiac_cursor_success_80_skewed_no_escrow`).
4. **LIVE** open as usual — next `open_clmm_candidate` uses brainiac ticks + two-sided inventory.

### Python

```python
from raydium_lp1.lp_brainiac_cursor_success import (
    open_clmm_with_brainiac_cursor_success,
    brainiac_optimal_wide_placement,
)

plan = brainiac_optimal_wide_placement(pool_row)
result = open_clmm_with_brainiac_cursor_success(
    pool_id="CXuK5H4TZgb28vuucNoJh8LXRmR4VjdEuL6pXmMenSod",
    input_amount_usd=15.0,
)
```

### Full pool rebalance script

```bash
python scripts/rebalance_sol_idle_brainiac.py --new-positions 4
python scripts/rebalance_sol_idle_brainiac.py --complete-opens-only
```

---

## Files touched

| File | Role |
|------|------|
| `lp_brainiac_cursor_success.py` | Core order-type logic |
| `lp_order_strategies.py` | Catalog + `build_open_order` branch |
| `lp_open_style.py` | LIVE kwargs resolver (skips pay-only) |
| `live_executor.py` | Forces inventory + two-sided for this strategy |
| `spend_less_get_more.py` | Disables wide→single-sided fallback |
| `super_brainiac/possibilities.py` | Scoring + in-range model for this placement |
| `lp_strategy_guide.py` | Dashboard strategy card copy |
| `scripts/rebalance_sol_idle_brainiac.py` | Procedure CLI (uses module) |

---

## Success criteria (for future runs)

- [ ] `sunk_sol_est == 0` in SPEND LESS rent block for each open  
- [ ] `wide_pay_only_single_side_fallback` is **absent** on success rows  
- [ ] `permanent_loss_usd.network_fees_only` ≪ total deposit USD  
- [ ] Band ticks match `brainiac_placement.tick_lower_pct_below` / `tick_upper_pct_above`  
- [ ] Both SOL and alt balances decrease on open (two-sided fill)
