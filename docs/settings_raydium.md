# Raydium list UI vs scanner settings

The public Raydium pool browser (for example `sort_by=fee`) mixes a very long tail of
micro pools with a smaller set of deep books. The scanner cannot shrink Raydium’s
catalog, but it can **classify rejects sensibly** and **gate on depth before APR**.

## Why APR rejects looked overwhelming

Previously, **APR was checked before TVL and 24h volume**. A pool with trivial depth
but APR `0.01` still produced `apr … below …` as the **first** rejection reason, so
histograms and CSV `first_reason` columns looked APR-dominated even when the real
problem was liquidity.

**Current order (high level):** require pool id → hard TVL exit → **min TVL** → **min
24h volume** → min APR → quotes / blocks / age / burn → …

So dust rows now surface as **liquidity** or **volume** rejects first, which matches
how humans skim Raydium (TVL and activity before yield).

## Practical floors (starting points, not advice)

| Goal | `min_liquidity_usd` | `min_volume_24h_usd` | `momentum_min_tvl_usd` | `min_apr` |
|------|--------------------|----------------------|-------------------------|-----------|
| Cut obvious dust | 5k–25k | 5k–25k | Match or exceed `min_liquidity_usd` | After gates, step down from your old floor |
| Majors + liquid alts | 250k–2M | 50k–500k | Same order of magnitude as min TVL | Often 25–45 once depth is real |
| Fee-sorted exploration | Keep pages small (`pages` 2–5); widen TVL before lowering APR | | | |

Use **`hard_exit_min_tvl_usd`** for a hard safety line (exit depth), and **`min_liquidity_usd`**
for the economic “this pool is worth my time” line. They can differ: hard exit can be
lower if you only want to block dangerously thin books.

## Mapping common Raydium URL knobs

| Raydium UI idea | Scanner keys |
|-----------------|--------------|
| Sort column | `pool_sort_field` (empty → falls back to `apr_field`) |
| Direction | `sort_type` (`desc` / `asc`) |
| Page size | `page_size` |
| How many pages | `pages` |
| Pool type filter | `pool_type` |

## Momentum block (dashboard labels)

Align **sweet min / max pool age** with how long you want pools to “prove” themselves
after launch. **Min Vol/TVL** (for example `0.5`) removes pools that show TVL but almost
no turnover. **`require_momentum_score`** makes the score a veto, not just a sort key.

## Routes

**`max_route_price_impact_pct`** in the ~1–5% range is typical; 5% is loose for small
clips on illiquid legs. **`route_sources_json`** defaults to Jupiter plus Raydium in
the dashboard display when unset.
