# CLMM / concentrated LP placement (paper layer)

Raydium-LP1 is **dry-run first**. This repo now includes **`lp_range_planner.py`**: it
turns **live list metrics** (TVL, 24h volume, `day.priceMin` / `day.priceMax` when
Raydium sends them, momentum + detective blobs) into **suggested price bands** and
**budget splits** (concentrated vs optional full-range leg). Nothing here signs a
transaction.

## What “sweet spot” means in code

- **Width % (`lp_default_range_width_pct` + `lp_range_width_candidates`)**  
  Candidate widths (e.g. 12 / 20 / 30 / 50) are **scored** from churn (vol/TVL) and
  daily price swing when `day.priceMin` / `day.priceMax` exist. Wider when the pool
  is already swinging; tighter when it is quiet (fee vs IL trade-off; **not** a
  profit guarantee).

- **Skew** (asymmetric band)  
  Uses **momentum + detective** `inflow_bias` and tags such as volume surge to
  **shift** the band so more room sits **above** spot when bias is positive (and
  the inverse when negative). Implementation: `asymmetric_quote_band()` in
  `lp_range_planner.py`.

- **Parallel “full range” leg**  
  Optional second leg with `lp_full_range_budget_fraction` of your position SOL
  (paper only). Real implementation must use the correct Raydium instruction for
  **full-range CLMM** or **CPMM** add-liquidity.

## What is still required for “live pennies”

1. **Exact price & tick math** — Read pool state (`sqrtPriceX64`, `tickCurrent`,
   `tickSpacing`) from on-chain CLMM accounts, **not** only the REST list.
2. **Transaction builder** — Compose Raydium SDK / instruction sets for “open
   position + add liquidity” with your wallet.
3. **Slippage & failure modes** — Match settings to `max_route_price_impact_pct` and
   RPC simulation before send.
4. **Per-mint cap enforcement** — Settings `lp_max_positions_per_mint` + a durable
   store (`lp_slots.py` stub today; wire when execution exists).

## Outputs

- Each passing candidate may include **`lp_placement_plan`** (JSON) when
  `lp_planning_enabled` is true.
- Aggregated file: **`reports/lp_placement_latest.json`**.

## CLMM “sweet spot” mode (settings)

Set **`lp_range_mode`** to **`clmm_dynamic_sweet_spot`** to reuse the live-data width scorer from `auto`, but snap widths only to **`lp_sweet_spot_width_candidates`** (default **8 / 20 / 40**). This is still **Raydium CLMM concentrated liquidity** (custom price range; asymmetric deposits) in Raydium’s vocabulary — not a separate on-chain program.

- **`lp_band_edge_buffer_pct`** (e.g. **3**) widens the suggested band slightly *outside* the API-derived spot (paper slack before real tick math).
- **`lp_single_sided_zap_deposit`**: when true, plans assume a **zap / single-sided deposit** path (pay SOL, USDC, USDT, USD1, … only; swap to ratio then add liquidity). Execution is **not** wired in this repo; it tags `lp_placement_plan.raydium_clmm_terms` for downstream builders.

## Wizard / settings

See `lp_*` and `risk_profile` keys in `settings_schema.py`, wizard prompts in
`scripts/setup_wizard.ps1`, and templates under `config/`.

## Momentum “sniffer” status

The dashboard / scanner already expose **TOP N HOT** pools (`momentum_top_hot`,
default **25**) and **`momentum_detective.fetch_market_pulse`** for Raydium
leaderboards — that work predates this document; enable `strategy=momentum` and
`momentum_detective_enabled=true` in settings.
