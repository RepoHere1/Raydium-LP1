# How Raydium filters their `/liquidity-pools/` UI — and how Raydium-LP1 mirrors it

Source: the `https://api-v3.raydium.io/pools/info/list` endpoint that powers
[raydium.io/liquidity-pools/](https://raydium.io/liquidity-pools/). Every
field below was confirmed by directly inspecting a live response.

Raydium-LP1 reads the same endpoint, parses the same fields, and exposes a
filter for each one.

## 1. Pool type (`type`)

Raydium splits pools into two top-level buckets:

- `"Standard"` — AMM v4 / CPMM pools (constant-product market makers).
- `"Concentrated"` — CLMM pools (Uniswap-v3-style concentrated liquidity).

The UI lets you switch tabs to filter to one or the other.

**LP1 setting:** `"pool_type": "all" | "concentrated" | "standard"` (passed
straight through to the API). Per-pool, the normalized field is `type` and
`subtypes` (e.g. `["Cpmm"]`).

## 2. Sort field (`poolSortField`)

The UI exposes ten sort options the API accepts directly:

```
default, liquidity, volume24h, volume7d, volume30d,
fee24h, fee7d, fee30d, apr24h, apr7d, apr30d
```

The default tab sorts by `liquidity` desc. The "high APR" view sorts by
`apr24h` desc — that's what LP1 uses by default.

**LP1 settings:** `"apr_field": "apr24h"` (or 7d/30d), `"sort_type": "desc"`.

**Separate list-order knob:** `"pool_sort_field": ""` (empty) leaves legacy behavior
(the API sorts by the same string as `apr_field`). Set `"pool_sort_field": "volume24h"`
or `"liquidity"` to page Raydium in a different order while still reading APR thresholds
from `apr_field`. See `raydium_pool_sort_param()` in `scanner.py`.

## 3. TVL / liquidity (`tvl`)

`tvl` is a top-level float in USD. Raydium's UI hides pools below a small
threshold (varies by tab). For brand-new pools the value can be `$0.01`
because the underlying token has no price discovery yet.

**LP1 setting:** `"min_liquidity_usd"` and the `min_liquidity` per-strategy
preset.

## 4. Volume / fees / APR — nested under period objects

This is the one that bit us. The response uses:

```jsonc
{
  "day":   { "volume": ..., "volumeFee": ..., "apr": ..., "feeApr": ..., "rewardApr": [..] },
  "week":  { "volume": ..., "apr": ..., "feeApr": ..., "rewardApr": [..] },
  "month": { "volume": ..., "apr": ..., "feeApr": ..., "rewardApr": [..] }
}
```

`apr` is total APR; `feeApr` is just trading-fee APR; `rewardApr` is an
array of farm-emission APRs. Raydium UI shows the total APR by default and
breaks it down on hover.

**LP1 fix:** `pool_apr()` reads `day.apr` (or `week.apr` / `month.apr`),
falling back to `feeApr + sum(rewardApr)`. `pool_volume()` and
`pool_fee_24h()` read `day.volume` and `day.volumeFee`. **Before this fix,
LP1 was reading nonexistent flat keys and every pool's APR/volume came
back as 0**, which is why a degen scan returned 0 candidates out of 25 000
pools.

## 5. Pool age (`openTime`)

Unix-seconds timestamp of pool creation. CLMM pools sometimes return `"0"`
when the creation timestamp is unavailable.

Raydium's UI surfaces "New Pools" using this field. You can replicate the
"give me only pools < 24h old" view this way.

**LP1 settings:**

- `"max_pool_age_hours": 24` — only pools younger than 24 hours pass.
- `"min_pool_age_hours": 1` — skip ultra-fresh pools that may not even have
  any swap volume yet.

Pools with `openTime = 0` are **not** filtered out (we have no signal).

## 6. LP burn percent (`burnPercent`)

`100` means the LP tokens were burned after the pool was seeded — the
creator literally cannot pull liquidity. `0` means LP tokens are
unrestricted. Pumpfun migrations typically come over with `burnPercent=100`.

This is a strong (but not perfect) anti-rug signal: a fully-burned LP can
still rug via a mint authority on the SPL token itself, but it can't rug
via liquidity withdrawal.

**LP1 setting:** `"min_burn_percent": 100` (or `50`, etc.). Per-pool
visible as `burn=100%` in the green/red stream output.

## 7. Pumpfun migrations (`launchMigratePool`)

`true` when the pool was created by Pumpfun's "graduation" process. These
pools start with a fixed initial liquidity profile.

**LP1:** exposed as `launch_migrate_pool` on the normalized pool dict; no
filter yet, but can be used in custom filters or future strategy presets.

## 8. Fee rate (`feeRate`)

Per-swap fee as a float, e.g. `0.04` = 4% / swap (which is hilariously high
and a strong sign of a Pumpfun memecoin pool).

**LP1:** exposed as `fee_rate` on the normalized pool dict.

## 9. Token metadata (`mintA` / `mintB`)

Each side gives:

- `address` — SPL mint
- `symbol` — display symbol. **Raydium returns wrapped SOL as `"WSOL"`,
  LP1 aliases this to `"SOL"`** so the default `allowed_quote_symbols`
  filter actually matches.
- `name`, `decimals`
- `programId` — `TokenkegQ…` is standard SPL, `TokenzQdBN…` is Token-2022
  (which can carry transfer fees / freeze authorities).
- `tags` — Raydium-curated labels.

**LP1:** `allowed_quote_symbols`, `blocked_token_symbols`, `blocked_mints`.
The normalized pool dict also exposes `mint_a_tags` / `mint_b_tags` so
later strategies can require a `verified` tag.

## 10. Farm reward badges (`farmOngoingCount` / `farmUpcomingCount`)

How many farm reward streams the pool currently has running or about to
start. The UI shows a 🟢 badge when > 0.

**LP1:** exposed as `farm_ongoing` on the normalized pool dict (no filter
yet, but available for custom rules).

---

## Putting it together — an actual aggressive setup

```jsonc
{
  "dry_run": true,
  "strategy": "aggressive",   // APR>=777, TVL>=$500, Vol>=$100
  "apr_field": "apr24h",
  "sort_type": "desc",
  "pool_type": "all",
  "page_size": 100,
  "pages": 3,                 // scan top 300 pools by APR

  "allowed_quote_symbols": ["SOL", "USDC", "USDT"],

  "max_pool_age_hours": 24,   // mirror Raydium's "New Pools" tab
  "min_pool_age_hours": 0.25, // skip the first 15 minutes (no signal yet)
  "min_burn_percent": 100,    // require LP burned (anti-rug heuristic)

  "require_sell_route": true, // Jupiter / Raydium must price an exit
  "use_robust_routing": true, // multi-source best-price route picker
  "emergency_close_enabled": true,
  "emergency_max_slippage_pct": 0.30,

  "position_size_sol": 0.1,
  "reserve_sol": 0.02
}
```

Run with the green/red stream visible:

```powershell
.\run_scan.ps1 --show-rejects 50
```

The rejection breakdown that prints at the end tells you which knob to
turn first.
