# Raydium-LP1 — command reference

All commands assume the repository root as the current directory. On Windows, use **PowerShell** from the repo root (or the root shortcuts `.\run_scan.ps1` / `.\setup_wizard.ps1`).

## Git: sync this folder to the latest agent branch

From your clone (example path — use yours):

```powershell
cd C:\Users\Taylor\Raydium-LP1
git fetch origin
git checkout cursor/live-wizard-mint-safety-2e5b
git pull origin cursor/live-wizard-mint-safety-2e5b
```

If the branch only exists on the remote:

```powershell
git fetch origin
git checkout -B cursor/live-wizard-mint-safety-2e5b origin/cursor/live-wizard-mint-safety-2e5b
```

If you have local edits, **commit** them or **`git stash -u`** before `git pull` so Git does not abort.

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

By default, `scripts\run_scan.ps1` opens the local dashboard at **http://127.0.0.1:8844/** in a Windows Terminal tab. Use **`-NoSpawnDashboardTab`** or **`"spawn_dashboard_web": false`** in `config\settings.json` to skip (for example if port 8844 is already in use).

```powershell
.\scripts\run_scan.ps1 -Loop -Interval 60 -WriteReports -SpawnWatcher -NoSpawnDashboardTab
```

With **`spawn_dashboard_web": false`** in `config\settings.json`, the script skips the dashboard tab unless you pass **`-SpawnDashboardTab`** for that run.

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

Use both `--host` and `--port`; a lone trailing `-` on the command line is parsed as a separate (invalid) argument. `python -m raydium_lp1.dashboard_web --help` shows the full syntax.

Then open `http://127.0.0.1:8844/` in your browser. With **`.\scripts\run_scan.ps1 -Loop`**, the script passes **`--dashboard --reload-config-each-scan`** so the funnel JSON and settings stay in sync with the web UI each cycle.

`run_scan.ps1` prints this URL at startup. Companion processes use `wt -w 0 nt` (window `0` / `last` = most recently used Windows Terminal window per [Microsoft’s wt.exe docs](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments)). The script starts `wt.exe` without shell execute so the child inherits the normal process environment and tabs land in the terminal instance you launched the scan from.

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
