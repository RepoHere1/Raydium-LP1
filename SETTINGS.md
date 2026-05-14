# Raydium-LP1 settings cheat sheet

All of your runtime settings live in **one file** that you can edit in Notepad or VS Code:

```text
C:\Users\Taylor\Raydium-LP1\config\settings.json
```

If that file doesn't exist yet, run the setup wizard once and answer the prompts.
The wizard now **remembers your previous answers and uses them as the defaults**
the next time you run it, so you only have to retype the things you want to change.

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\scripts\setup_wizard.ps1
```

There are **nine named pieces of logic**, each in its own module and with its
own section in `settings.json`. JSON does not allow real comments, so the
example file uses `"_comment_*"` keys to hold short notes — feel free to delete
them, the scanner ignores any key it does not recognise.

| # | Feature | What it asks | Cost |
| --- | --- | --- | --- |
| 1 | `survival_runway` | Will the pool still be alive in 3–7 days? | snapshot only |
| 2 | `quote_only_entry` | Never buy the unknown token at entry. | snapshot only |
| 3 | `honeypot_guard` | Sell tax / freeze / hook / permanent delegate. | 1 RPC per base mint |
| 4 | `pool_age_guard` | Is the pool too young (or too old) to enter? | snapshot only |
| 5 | `mint_authority_guard` | Can the creator mint unlimited new supply? | shares honeypot RPC |
| 6 | `lp_lock_guard` | Is LP supply burned/locked so liquidity can't be pulled? | 2 RPC per LP mint |
| 7 | `price_impact_guard` | Will our entry crater the price? | snapshot only |
| 8 | `fee_apr_floor` | Is the headline APR carried by fees, or just farm rewards? | snapshot only |
| 9 | `rpc_health_gate` | Refuse to scan if no Solana RPC actually answers. | `getHealth` per RPC |

---

## 1. `survival_runway` — "will this pool still be alive in 3–7 days?"

A pool with 5000% APR is useless if it dies tomorrow. This filter keeps only
pools that look like they can keep paying for at least the number of days you
set.

```json
"survival_runway": {
  "enabled": true,
  "target_survival_days": 5,
  "min_tvl_multiple_of_position": 200,
  "min_daily_volume_pct_of_tvl": 5.0,
  "require_active_week": true
}
```

| Setting | Meaning | Bigger value = |
| --- | --- | --- |
| `enabled` | Turn the survival-runway filter on/off. | — |
| `target_survival_days` | How long you want the position to survive (3 = three days, 7 = a week). This is documentation today; the math below is what actually gates pools. | — |
| `min_tvl_multiple_of_position` | Pool TVL must be at least this many times your `max_position_usd`. With defaults: `25 * 200 = $5000` TVL floor. | Safer, fewer candidates. |
| `min_daily_volume_pct_of_tvl` | Pool's 24h volume must be at least this percent of its TVL. Low ratio = pool is dead; fees won't sustain LPs. | Safer, fewer candidates. |
| `require_active_week` | Only keep pools that already have nonzero weekly volume. Screens 5-minute-old rugs. | Safer; brand-new pools fail. |

Want to be aggressive? Set `min_tvl_multiple_of_position` to `40` and
`min_daily_volume_pct_of_tvl` to `1.0`. Want to be conservative? `500` and
`20.0`.

---

## 2. `quote_only_entry` — "never buy their stupid token at the start of a position"

Every Raydium pool has two sides. One side is something you trust (SOL, USDC,
USDT, USD1). The other side is the random token whose APR drew us in. This
policy says: at entry, you **only deposit the side you trust**. You never swap
your safe asset into the unknown token at entry. (If the pool's price moves
against you while the position is open, the AMM may convert some of your quote
into the base token as a side effect — that is normal LP behaviour, not a buy.)

```json
"quote_only_entry": {
  "enabled": true,
  "allowed_quote_symbols": ["SOL", "USDC", "USDT", "USD1"],
  "require_concentrated_pool": false,
  "allow_quote_quote_pools": true
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the policy on/off. |
| `allowed_quote_symbols` | The list of tokens you are willing to deposit. Edit this freely. |
| `require_concentrated_pool` | If true, only Raydium **Concentrated / CLMM** pools qualify. CLMM pools can accept a truly one-sided deposit; classic AMM v4 pools cannot. Turn this on the day you wire up real deposits. |
| `allow_quote_quote_pools` | Allow stable/stable pools like USDC/USDT (both sides are "safe"). |

This is also the source-of-truth list for the filter that earlier just called
itself `allowed_quote_symbols`. They are kept in sync but
`quote_only_entry.allowed_quote_symbols` is the one that controls the
"never buy their token" rule.

---

## 3. `honeypot_guard` — "sell-tax cap + freeze/hook/permanent-delegate vetoes"

This is the on-chain safety check. For each candidate, the scanner makes one
Solana RPC call to read the mint account of the *base* token (the non-quote
side) and looks at four things:

1. **Sell tax / transfer fee.** Token-2022 supports a `TransferFeeConfig`
   extension that takes a percentage of every transfer. That is *the* on-chain
   "sell tax" / "sell slippage by design". We read the current basis points
   and reject the pool if the implied percent is above `max_sell_tax_percent`.
2. **Freeze authority.** A token whose mint has a freeze authority can have
   its accounts frozen by the issuer. We reject by default. The legit
   stables USDC + USDT both have freeze authority on purpose; their mint
   addresses are in `allowed_freeze_authority_mints` so they don't trip the
   guard.
3. **Transfer hook.** Token-2022's `TransferHook` extension lets the issuer
   point at a program that runs on every transfer. That program can revert
   any sell — the textbook honeypot. Rejected by default.
4. **Permanent delegate.** Token-2022's `PermanentDelegate` extension lets the
   delegate move tokens out of *any* account. Rejected by default.

```json
"honeypot_guard": {
  "enabled": true,
  "max_sell_tax_percent": 30.0,
  "reject_if_freeze_authority_set": true,
  "reject_if_transfer_hook_set": true,
  "reject_if_permanent_delegate_set": true,
  "allowed_freeze_authority_mints": [
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
  ],
  "fail_open_when_no_rpc": false,
  "rpc_timeout_seconds": 8.0
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the honeypot guard on/off. |
| `max_sell_tax_percent` | Upper bound on the on-chain transfer fee. Your requested limit is `30.0` = 30%. Anything above this is rejected. |
| `reject_if_freeze_authority_set` | If true, mints with a non-empty freeze authority are rejected unless their mint address is in `allowed_freeze_authority_mints`. |
| `reject_if_transfer_hook_set` | If true, mints with a `TransferHook` extension are rejected. |
| `reject_if_permanent_delegate_set` | If true, mints with a `PermanentDelegate` extension are rejected. |
| `allowed_freeze_authority_mints` | Explicit whitelist for tokens whose freeze authority you trust (e.g. USDC, USDT mints). |
| `fail_open_when_no_rpc` | If true and no Solana RPC is configured or all configured RPCs fail, candidates pass anyway. Default `false` = safer; "if we can't check, we don't enter." |
| `rpc_timeout_seconds` | Per-RPC timeout for the mint lookup. |

The RPC URLs come from `.env` (`SOLANA_RPC_URL` and `SOLANA_RPC_URLS`). The
wizard remembers them. If your free public RPC keeps timing out, paste a
Helius / Chainstack / dRPC / GetBlock URL in the wizard's "Backup RPC URL"
prompt.

---

## 4. `pool_age_guard` — "is this pool old enough to trust?"

Brand-new pools regularly post 999%+ APR for a few minutes and then collapse,
because the math `apr = recent_fees * 365` blows up any short window into a
huge annual number. This guard rejects pools that are younger than
`min_age_minutes`, and (optionally) older than `max_age_days` if you only
want fresh pools.

```json
"pool_age_guard": {
  "enabled": true,
  "min_age_minutes": 60,
  "max_age_days": 0,
  "fail_open_when_unknown": false
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the age check on/off. |
| `min_age_minutes` | Pool must have existed at least this many minutes. Default `60`. |
| `max_age_days` | Reject pools older than this many days. `0` = no cap. |
| `fail_open_when_unknown` | If Raydium's snapshot has no `openTime`, accept by default? Default `false` (= reject). |

---

## 5. `mint_authority_guard` — "can the creator mint unlimited new supply?"

If the base token's `mint_authority` is still set, somebody can mint a fresh
billion units of the token at any time and dump it into the pool. That is the
fastest hard-rug pattern on Solana. Safer state: the mint authority has been
disabled. This guard reuses the `getAccountInfo` call that `honeypot_guard`
already makes, so enabling both costs only one RPC per base mint per scan.

```json
"mint_authority_guard": {
  "enabled": true,
  "reject_if_mint_authority_set": true,
  "allowed_mint_authority_mints": [
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
  ],
  "fail_open_when_no_rpc": false
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the mint-authority check on/off. |
| `reject_if_mint_authority_set` | If the mint authority is `Some(...)` (somebody can still mint), reject unless whitelisted. |
| `allowed_mint_authority_mints` | Tokens that *should* have a live mint authority (e.g. USDC, USDT). |
| `fail_open_when_no_rpc` | If true, candidates pass when no RPC is configured or all RPCs fail. Default `false`. |

---

## 6. `lp_lock_guard` — "can the creator pull the liquidity out from under us?"

After launch, whoever holds the LP tokens controls the pool's liquidity. If the
team kept the LP tokens, they can withdraw the whole pool in one transaction
("soft rug"). The defence is to require that a high fraction of LP supply has
been burned (sent to the incinerator address) or moved to a locker program.

This guard reads the LP mint's total `supply` and the LP balance held at the
known incinerator address (`1nc1nerator1111…`). The fraction held by the
incinerator counts toward "burned/locked". When Raydium's snapshot itself
exposes a `burnPercent` field we use that directly. Concentrated/CLMM pools
use NFT positions instead of fungible LP tokens; this guard skips CLMM pools
by default and only enforces them when you set `apply_to_concentrated_pools`.

```json
"lp_lock_guard": {
  "enabled": true,
  "min_locked_or_burned_pct": 90.0,
  "apply_to_concentrated_pools": false,
  "fail_open_when_no_rpc": false,
  "rpc_timeout_seconds": 8.0
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the LP-lock check on/off. |
| `min_locked_or_burned_pct` | Required percentage of LP supply that's burned or locked. Default `90.0`. |
| `apply_to_concentrated_pools` | If `true`, also enforce on CLMM pools (whose LP model is different). |
| `fail_open_when_no_rpc` | If true, candidates pass when no RPC is configured or all RPCs fail. |
| `rpc_timeout_seconds` | Per-RPC timeout for the supply / incinerator-balance calls. |

---

## 7. `price_impact_guard` — "will our $25 entry crater the price?"

Sliced through the math, in a constant-product AMM with quote-side reserve
`x` the price impact of an additive trade `dx` is `dx / (x + dx)`. With
`max_position_usd = 25` and a $5M-TVL pool this is well under 0.001%. With a
$50-TVL pool it is around 33%. This guard estimates impact from TVL alone
(assuming a 50/50 split, configurable) and rejects pools where impact is
above `max_impact_percent`.

```json
"price_impact_guard": {
  "enabled": true,
  "max_impact_percent": 1.0,
  "quote_side_fraction": 0.5
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the impact estimator on/off. |
| `max_impact_percent` | Reject pools where the estimated entry impact exceeds this percentage. |
| `quote_side_fraction` | How much of TVL we treat as the quote-side reserve. `0.5` for AMM v4; bump down to be conservative on CLMM. |

This filter is pure — no extra API call, just math on the snapshot the scanner
already pulled.

---

## 8. `fee_apr_floor` — "is the APR real, or carried by farm rewards?"

Raydium's headline APR usually mixes real trading fees and short-window
reward-token emissions. Fee-only APR (≈ `fee_24h * 365 / TVL`) is what
survives after rewards stop. This filter rejects pools whose fee-only APR is
below the floor — those rely on rewards that can end at any time.

```json
"fee_apr_floor": {
  "enabled": true,
  "min_fee_apr_percent": 30.0
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the fee-APR floor on/off. |
| `min_fee_apr_percent` | Minimum acceptable fee-derived APR (in percent). |

---

## 9. `rpc_health_gate` — "stop if no RPC is actually answering"

Three of the safety checks above (`honeypot_guard`, `mint_authority_guard`,
`lp_lock_guard`) call a Solana RPC. If your configured RPCs are all dead or
rate-limited, those guards either fail open (silently letting risky pools
through) or fail closed (rejecting every candidate) without telling you. The
gate samples them with `getHealth` before scanning and aborts the run with a
clear message unless at least `min_healthy_rpcs` come back OK.

```json
"rpc_health_gate": {
  "enabled": true,
  "min_healthy_rpcs": 1,
  "require_when_no_rpc_configured": false
}
```

| Setting | Meaning |
| --- | --- |
| `enabled` | Turn the gate on/off. |
| `min_healthy_rpcs` | Number of RPCs that must answer `getHealth` before scanning. |
| `require_when_no_rpc_configured` | If `true`, also fail when no RPCs are configured at all. Default `false` so you can run the scanner with no RPCs. |

The gate prints a one-line summary, e.g. `RPC health gate: 2/3 healthy (need 1)`.

---

## Scanner output you'll now see

When you run `.\scripts\run_scan.ps1 -CheckRpc -WriteReports` the text report
now prints:

- the active settings for **all nine** filters
- the candidate list with a `HoneypotGuard:` line under each pool showing what
  was read on-chain (token-2022 flag, sell tax %, freeze, mint authority,
  hook, perm delegate) and a `LpLockGuard:` line with the burned/locked
  percentage
- the `RPC health gate` line summarising how many of your configured RPCs
  answered before scanning started
- per-category rejection counts when nothing passes, e.g.
  `honeypot_guard_failed: 12, survival_runway_failed: 41, pool_age_guard_failed: 8, ...`
- the top 5 pools by APR pre-filter, so you can decide whether to relax
  `min_apr` or one of the nine named filters

The JSON report (`reports/latest.json`) contains the same data plus a
`honeypot_inspection` and `lp_lock_inspection` block on each candidate and a
global `active_filters` section listing all nine filters' settings, so other
tools can read your decisions.

---

## "Just give me the safest defaults"

Edit `config\settings.json` and set:

```json
"min_apr": 100.0,
"min_liquidity_usd": 5000,
"min_volume_24h_usd": 1000,
"pages": 5,
"survival_runway": {
  "enabled": true,
  "target_survival_days": 7,
  "min_tvl_multiple_of_position": 400,
  "min_daily_volume_pct_of_tvl": 10.0,
  "require_active_week": true
},
"honeypot_guard": {
  "enabled": true,
  "max_sell_tax_percent": 5.0,
  "reject_if_freeze_authority_set": true,
  "reject_if_transfer_hook_set": true,
  "reject_if_permanent_delegate_set": true,
  "fail_open_when_no_rpc": false
},
"pool_age_guard": {
  "enabled": true,
  "min_age_minutes": 1440,
  "max_age_days": 0,
  "fail_open_when_unknown": false
},
"mint_authority_guard": {
  "enabled": true,
  "reject_if_mint_authority_set": true,
  "fail_open_when_no_rpc": false
},
"lp_lock_guard": {
  "enabled": true,
  "min_locked_or_burned_pct": 95.0,
  "apply_to_concentrated_pools": false,
  "fail_open_when_no_rpc": false
},
"price_impact_guard": {
  "enabled": true,
  "max_impact_percent": 0.5
},
"fee_apr_floor": {
  "enabled": true,
  "min_fee_apr_percent": 50.0
},
"rpc_health_gate": {
  "enabled": true,
  "min_healthy_rpcs": 1
}
```

That is "high enough APR to be interesting, $10k+ TVL, traded for at least a
week, deep daily turnover, no Token-2022 traps, no live mint authority, LP
burned/locked, small enough position to barely move price, fee APR carries the
yield on its own, and if my RPC is down I don't enter blind."
