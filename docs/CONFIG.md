# Where your settings live (Git vs your PC)

## On GitHub (in the repo)

| File | Purpose |
|------|---------|
| `config/settings.example.json` | **Template** — every supported key with safe defaults. Copy this to start. |
| `config/settings.momentum.example.json` | **Momentum / fee-rush preset** — copy or merge for your hunting profile. |
| `config/filters.example.json` | Legacy alternate example (older layout). Prefer `settings.example.json`. |

`config/settings.json` is **not** in Git (see `.gitignore`). That is intentional so your RPC keys and tuned filters stay on your machine.

## On your Windows PC (what the scanner actually reads)

| File | Purpose |
|------|---------|
| `config\settings.json` | **Live config** — `run_scan.ps1` and the wizard use this path by default. |
| `.env` | RPC URLs, wallet address (secrets; not committed). |

If you only see `settings.example.json` on GitHub but `settings.json` on `C:\...\Raydium-LP1`, that is correct. The scanner does **not** read the `.example` file unless you pass `--config` to it.

## Invalid JSON (`JSONDecodeError` on line 26, etc.)

The scanner requires **strict JSON** in `config\settings.json`. A missing comma after a line, a trailing comma on the last key, or `//` comments will stop the scan immediately (the watcher window may still open, but Window 1 exits).

```powershell
.\scripts\doctor.ps1
.\scripts\repair_settings.ps1 -ApplyMomentumTemplate
```

That backs up your broken file to `config\settings.json.bak` and replaces it with the known-good momentum template. Settings sync/wizard now write JSON through Python so `ConvertTo-Json` depth bugs are less likely.

## One-time: align local `settings.json` with momentum

```powershell
cd C:\path\to\Raydium-LP1
.\scripts\sync_settings.ps1 -ApplyMomentumTemplate
```

Or run the wizard:

```powershell
.\scripts\setup_wizard.ps1
```

Choose strategy **`momentum`** or **`fee_rush`**.

## Verify the running config

```powershell
.\scripts\doctor.ps1
python scripts\scan_raydium_lps.py --config config\settings.json --json 2>$null | Select-String momentum
```

After a scan, open:

- `reports\dashboard.json` — includes `momentum_hot_top` (top 25 HOT)
- `reports\momentum_sniffer.json` — full detective breakdown per pool
- `reports\latest.json` — all candidates with `momentum` objects

## Momentum keys (all in `settings.json`)

```json
"strategy": "momentum",
"min_liquidity_usd": 5000,
"hard_exit_min_tvl_usd": 1000,
"momentum_enabled": true,
"min_momentum_score": 55,
"require_momentum_score": false,
"momentum_hold_hours": 24,
"momentum_min_volume_tvl_ratio": 0.5,
"momentum_sweet_min_pool_age_hours": 6,
"momentum_sweet_max_pool_age_hours": 168,
"momentum_min_tvl_usd": 5000,
"momentum_top_hot": 25,
"momentum_detective_enabled": true,
"momentum_probe_market_lists": true,
"sort_candidates_by_momentum": true
```
