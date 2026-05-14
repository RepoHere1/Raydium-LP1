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

There are three named pieces of logic you asked for. Each has its own section in
`settings.json`. JSON does not allow real comments, so the example file uses
`"_comment_*"` keys to hold short notes — feel free to delete them, the scanner
ignores any key it does not recognise.

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

## Scanner output you'll now see

When you run `.\scripts\run_scan.ps1 -CheckRpc -WriteReports` the text report
now prints:

- the active filter settings (so you can see what's on)
- the candidate list with a `HoneypotGuard:` line under each pool showing what
  was read on-chain (token-2022 flag, sell tax %, freeze, hook, perm delegate)
- per-category rejection counts when nothing passes, e.g.
  `honeypot_guard_failed: 12, survival_runway_failed: 41, ...`
- the top 5 pools by APR pre-filter, so you can decide whether to relax
  `min_apr` or one of the three named filters

The JSON report (`reports/latest.json`) contains the same data plus a
`honeypot_inspection` block on each candidate and a global `active_filters`
section, so other tools can read your decisions.

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
}
```

That is "high enough APR to be interesting, $10k+ TVL, traded for at least a
week, deep daily turnover, no Token-2022 traps, and if my RPC is down I don't
enter blind."
