# Raydium-LP1 — command reference

All commands assume the repository root as the current directory. On Windows, use **PowerShell** from the repo root (or the root shortcuts `.\run_scan.ps1` / `.\setup_wizard.ps1`).

## Python environment

```powershell
$env:PYTHONPATH = "src"
```

On Linux/macOS:

```bash
export PYTHONPATH=src
```

## First-time setup (Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_wizard.ps1
```

Or double-click `START_HERE_SETUP.bat`. When **Windows Terminal** (`wt.exe`) is installed, the wizard opens the **local dashboard** and (if you chose it) the **verdict watcher** in new **tabs** instead of separate console windows.

## Doctor (sanity check)

```powershell
.\scripts\doctor.ps1
```

## Live dry-run scan (main entry)

```powershell
.\scripts\run_scan.ps1 -CheckRpc -WriteReports
```

```powershell
.\scripts\run_scan.ps1 -Loop -Interval 60 -WriteReports -SpawnWatcher
```

```powershell
.\scripts\run_scan.ps1 -Loop -Interval 60 -WriteReports -SpawnWatcher -SpawnDashboardTab
```

With **`spawn_dashboard_web": true`** in `config\settings.json`, `run_scan.ps1` opens the local dashboard tab automatically (same as `-SpawnDashboardTab`). Close the old tab if port 8844 is already in use.

```powershell
.\scripts\run_scan.ps1 -Json
```

### Direct Python (any OS)

```powershell
python scripts\scan_raydium_lps.py --config config\settings.json --check-rpc --write-reports
```

```powershell
python scripts\scan_raydium_lps.py --config config\settings.json --loop --interval 60 --dashboard --reload-config-each-scan
```

```bash
python3 scripts/scan_raydium_lps.py --config config/settings.json --write-rejections
```

### Module form

```powershell
python -m raydium_lp1.scanner --config config\settings.json --check-rpc
```

## Local web dashboard (127.0.0.1)

```powershell
.\scripts\run_dashboard_web.ps1
```

```powershell
python -m raydium_lp1.dashboard_web --host 127.0.0.1 --port 8844
```

Then open `http://127.0.0.1:8844/` in your browser. Pair with a looping scanner using `--reload-config-each-scan` so edits to `settings.json` apply each cycle.

## Settings repair / sync

```powershell
.\scripts\repair_settings.ps1 -ApplyMomentumTemplate
```

```powershell
.\scripts\sync_settings.ps1
```

## RPC-only wizard

```powershell
.\scripts\rpc_wizard.ps1
```

## Unit tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Exit slippage / mint tax (defaults)

The scanner enforces, by default:

- **`max_route_price_impact_pct`** (default **15**) on Jupiter quote responses when sell routes are required.
- **`route_quote_max_slippage_bps`** (default **1500** = 15%) passed into Jupiter/Raydium quote URLs.
- **`enforce_mint_exit_safety`**: RPC **`getMultipleAccounts`** with **`jsonParsed`** on both pool mints — only standard **SPL Token / Token-2022** mint owners; **Token-2022 transfer fee** must not exceed **`max_transfer_fee_bps`** (default **1500**).

Tune or disable these in `config/settings.json` (see `config/settings.example.json`).
