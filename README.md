# Raydium-LP1

Raydium-LP1 is a **dry-run-first** scanner for finding Raydium liquidity pools whose reported APR is high, then running those pools through local safety filters before any future trade/liquidity-opening code is allowed to act.

The default APR filter is now **999.99%**, not ninety-nine thousand percent. You can change it any time in `config\settings.json` or by running the setup wizard again.

## What this script does so far

1. Reads live Raydium pool data from `https://api-v3.raydium.io`.
2. Uses Raydium's pool list endpoint `/pools/info/list`.
3. Sorts pools by `apr24h` from high to low.
4. Keeps only pools at or above your `min_apr` setting. Default: `999.99`.
5. Rejects pools that fail your local filters, such as low liquidity, low 24h volume, blocked tokens, or missing pool IDs.
6. Reads local RPC/API source settings from `.env`, without committing private API keys to GitHub.
7. Can check configured Solana RPCs with `getHealth` so you know whether your live data sources answer.
8. Can write reports to `reports\latest.json`, timestamped JSON files, and `reports\candidates.csv`.
9. Prints what it found in beginner-friendly text or JSON.
10. Does **not** buy, sign, use wallet keys, or open LP positions yet.







## If we need to transfer files in chunks

When GitHub is empty and direct push is blocked, we can transfer the project as Base64 ZIP chunks pasted into PowerShell. After extraction, GitHub Desktop will see the files and you can commit them as `Initial Raydium-LP1 files`.

Read the chunk workflow here: [`WINDOWS_FILE_MAKER_CHUNKS.md`](WINDOWS_FILE_MAKER_CHUNKS.md).

## If GitHub Desktop is connected but the folder has no files

GitHub Desktop can only commit files that are actually inside `C:\Users\Taylor\Raydium-LP1`. If that folder only has `.git`, GitHub Desktop is connected to an empty repo.

Use the focused transfer guide here: [`WINDOWS_ZIP_TRANSFER_GUIDE.md`](WINDOWS_ZIP_TRANSFER_GUIDE.md).

## If `git push` says `CONNECT tunnel failed, response 403`

That proxy error means the network running the push cannot reach GitHub. When it happened here, it was this coding container's network proxy blocking GitHub, not your Windows machine and not the Raydium-LP1 code.

Read the focused fix here: [`GITHUB_PUSH_PROXY_FIX.md`](GITHUB_PUSH_PROXY_FIX.md).

## If GitHub cloned empty / only `.git` appears

Your Windows output `warning: You appear to have cloned an empty repository` means GitHub has no project files yet. The setup wizard cannot run until the files exist in the Windows folder.

Also: when copying commands from Markdown, do **not** paste the ```powershell line or the closing ``` line into PowerShell. Paste only the command lines inside the box.

Read the focused fix here: [`WINDOWS_EMPTY_GITHUB_FIX.md`](WINDOWS_EMPTY_GITHUB_FIX.md).

## If your Windows folder is empty

If `C:\Users\Taylor\Raydium-LP1` is empty, the setup script cannot run yet because the project files are not on your PC. I am editing this repo in the coding workspace, not directly inside your Windows folder.

Read the full copy/paste guide here: [`GET_CODE_INTO_WINDOWS.md`](GET_CODE_INTO_WINDOWS.md).

Short version, after the code has been pushed to GitHub:

```powershell
cd C:\Users\Taylor
if (Test-Path .\Raydium-LP1) {
  Rename-Item .\Raydium-LP1 ("Raydium-LP1-empty-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
git clone https://github.com/RepoHere1/Raydium-LP1.git Raydium-LP1
cd .\Raydium-LP1
Get-ChildItem -Force
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```

## If PowerShell says `setup_wizard.ps1` is not recognized

You do **not** type `node` for this project. Node.js is for JavaScript apps. Raydium-LP1 uses **PowerShell** for the Windows helper scripts and **Python** for the scanner.

In PowerShell, scripts in the current folder must start with `.` and `\`. So this will fail:

```powershell
setup_wizard.ps1
```

Use this instead:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\setup_wizard.ps1
```

If Windows blocks the script, use the bypass form:

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```

### RPC-only wizard (fix `.env` / `solana_rpc_urls` without re-running full setup)

If `SOLANA_RPC_URLS` had a typo like a trailing `,y` (which crashed older scans), run:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\scripts\rpc_wizard.ps1
```

It rewrites `.env` with validated `https://` URLs and, if `config\settings.json` exists, merges the same list into `solana_rpc_urls`. Use `-SkipSettingsJson` to touch only `.env`.

**Correct `.env` shape** (each comma-separated fallback must be a full URL):

```text
RAYDIUM_API_BASE=https://api-v3.raydium.io
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY_HERE
SOLANA_RPC_URLS=https://solana-rpc.publicnode.com,https://solana.drpc.org
```

After setup, run the scanner with:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\run_scan.ps1 -CheckRpc -WriteReports
```

Or double-click:

```text
START_HERE_SCAN.bat
```

About the code box / panel moving on the right side: that is part of the coding workspace UI, not the Raydium-LP1 project files. I cannot change that UI from this repo. The safest workaround is to use the copy/paste PowerShell blocks in this README or double-click the `START_HERE_*.bat` files.

## Scanner exits instantly with `JSONDecodeError` around line 26

Your `config\settings.json` has invalid JSON (often a missing comma). `git pull`, then restore a known-good file:

```powershell
cd C:\Users\Taylor\Raydium-LP1
git pull origin main
.\scripts\repair_settings.ps1 -ApplyMomentumTemplate
.\scripts\run_scan.ps1 -Loop -SpawnWatcher -WriteRejections
```

## PowerShell says `Missing file specification after redirection operator` (`<<<<<<< HEAD`)

Unresolved Git merge conflict markers got saved inside a `.ps1` file (often `scripts\run_scan.ps1`). PowerShell reads `<<` as redirection. Replace that file from GitHub:

```powershell
cd C:\Users\Taylor\Raydium-LP1
git fetch origin main
git checkout origin/main -- scripts/run_scan.ps1 src/raydium_lp1/verdicts.py
```

Or reset the whole tracked tree when many files broke (usual after merging the wrong branch):

```powershell
cd C:\Users\Taylor\Raydium-LP1
git fetch origin
.\scripts\reset_to_main.ps1
```

(Type `RESET` when prompted.)

## Prefer `origin/main`; avoid random `pull origin cursor/*` unless you intend to test a branch.

Feature branches (`cursor/...`) can be stale or incompatible with each other; **your daily scanner should track `main`:**

```powershell
git fetch origin
git pull origin main
```

Pulling something like `git pull origin cursor/verdict-watcher-sync-dee0` mid-session can leave **unmerged files** and **`<<<<<<<`** markers inside `.py` files (then Python reports `SyntaxError` on that line).

If Git says **unmerged files** and you only want GitHub’s current app:

```powershell
git merge --abort   # only if a merge is in progress
git fetch origin
git reset --hard origin/main
```

(same effect as `reset_to_main.ps1`.)

### If PowerShell cannot find `.\scripts\reset_to_main.ps1`

That usually happens while **`git pull` never finished**: the merge failed, so newer files never landed locally. **`git fetch` already updated remote refs**, so force your tree to **`origin/main` without merging**:

```powershell
git merge --abort
git fetch origin
git reset --hard origin/main
```

Or double-click **`RESET_TO_ORIGIN_MAIN.bat`** in the repo root (uses `CMD`, not `.ps1`).

**After** `reset --hard`, `git pull origin main` will say "Already up to date" until the next upstream commit.

## Momentum scans show hundreds of rejects on `hard_exit_min_tvl_usd`

When Raydium pages are **`apr*` sorted** (default), the first pools are ultra-high APR dust with roughly **$0–$13 TVL** — they instantly fail **`hard_exit_min_tvl_usd`** (preset **1000**). That is the filter working, not a bug.

**Tunings (pick a few):**

1. Add **`"pool_sort_field": "volume24h"`** (or `"liquidity"`) in `config\settings.json` — new in this build; wizard asks for it.
2. **`"hard_exit_min_tvl_usd": 0`** turns off the exit-safety hard line (riskier); or lower (e.g. **200**) to match `aggressive` appetite.
3. **`"pages": 5`–`10`** only helps a little on APR-sorted lists; **changing `pool_sort_field` matters more** than brute-forcing more APR-sorted pages.
4. **`min_apr`**: keep it at **300% or higher** if you are not willing to watch lower-APR pools. For “more breathing room” vs dust, prefer **`pool_sort_field`** and **`pages`** (and momentum preset tuning) rather than lowering APR below that floor.
5. **Wallet balance** (live RPC in dry-run): **`max_positions=0`** is **planning-only** in dry-run — the full pass list still prints; it does **not** explain TVL rejects. Capacity **capping** applies when you run with **`dry_run: false`** (when enabled in your build).

## Live data sources

This project is designed to use real production data, not placeholders:

- Raydium REST API: `https://api-v3.raydium.io`
- Raydium pool list: `/pools/info/list`
- Optional Solana RPCs in `.env`: public RPCs, Helius, Chainstack, GetBlock, dRPC, etc.

Important: RPC URLs with API keys are secrets. Keep them in `.env`; do not paste them into `config\settings.json` if you plan to commit that file, and do not commit `.env`.

## Easiest Windows setup: double-click or paste

### Option A: double-click

From File Explorer, open your project folder:

```text
C:\Users\Taylor\Raydium-LP1
```

Then double-click:

```text
START_HERE_SETUP.bat
```

That opens PowerShell, asks you questions, creates `.env`, creates `config\settings.json`, and offers to run the doctor check.

After setup, you can double-click:

```text
START_HERE_SCAN.bat
```

### Option B: paste into PowerShell

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```

Then run a scan with live Raydium data and RPC checks:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\run_scan.ps1 -CheckRpc -WriteReports
```

If PowerShell blocks `.ps1` scripts, use this:

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_scan.ps1 -CheckRpc -WriteReports
```

## Settings page / wizard

For now, the "settings page" is the local file:

```text
config\settings.json
```

The setup wizard creates it for you. To change your APR threshold later, edit this line:

```json
"min_apr": 999.99
```

Or rerun the wizard:

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```

The safe example settings live in:

```text
config\settings.example.json          # full template (every key)
config\settings.momentum.example.json # fee-rush / momentum preset (TVL $5k, MOM 55, etc.)
config\filters.example.json           # legacy alternate example
```

Your **live** config is only on your PC: `config\settings.json` (ignored by Git). The scanner does **not** read the `.example` files unless you pass `--config` to them.

See **docs/CONFIG.md**. To apply the momentum preset on Windows:

```powershell
.\scripts\sync_settings.ps1 -ApplyMomentumTemplate
```

## Creating `.env` correctly

The wizard is the safest way. It creates `.env` like this:

```text
RAYDIUM_API_BASE=https://api-v3.raydium.io
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_RPC_URLS=https://solana-rpc.publicnode.com,https://solana.drpc.org
```

To add private provider URLs like Helius, Chainstack, GetBlock, or dRPC, paste them when the wizard asks for RPC URLs. The script loads them from `.env` automatically.

## Doctor check

Run this when something feels broken:

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\doctor.ps1
```

It checks the repo folder, scanner files, local settings, `.env`, Python, and Git remote branches.

## Running scans

The setup wizard can save **loop**, **verdict log watcher**, and **rejections CSV** choices into `config\settings.json` as **`scan_loop`**, **`scan_loop_interval_seconds`**, **`spawn_verdict_watcher`**, and **`write_rejections`**. A plain `.\run_scan.ps1` then applies those defaults; any flags you pass on the command line still win.

Normal beginner output:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\run_scan.ps1
```

Check RPCs first and write report files:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\run_scan.ps1 -CheckRpc -WriteReports
```

Print machine-readable JSON:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\run_scan.ps1 -Json
```

Poll repeatedly every 60 seconds. Press `Ctrl+C` to stop:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\run_scan.ps1 -Loop -Interval 60 -WriteReports
```

Direct Python fallback:

```powershell
cd C:\Users\Taylor\Raydium-LP1
python scripts\scan_raydium_lps.py --config config\settings.json --check-rpc --write-reports
```

## Filters

Defaults include:

- `min_apr`: `999.99`
- `min_liquidity_usd`: `1000`
- `min_volume_24h_usd`: `100`
- `allowed_quote_symbols`: `SOL`, `USDC`, `USDT`
- `max_position_usd`: `25`
- `dry_run`: `true`

A pool must pass every configured filter to show as a candidate.

## Troubleshooting the exact errors you saw

### `fatal: couldn't find remote ref main`

This means your GitHub repository does not currently have a branch named `main`. It usually means the repo is still empty online, or the code has not been pushed to GitHub yet.

Check remote branches:

```powershell
cd C:\Users\Taylor\Raydium-LP1
git ls-remote --heads origin
```

If nothing prints, GitHub has no branches yet. A pull cannot work until something is pushed.

### `.\run_scan.ps1 is not recognized`

This means the root shortcut `run_scan.ps1` or the scanner files are not in your Windows folder yet. Check it with:

```powershell
cd C:\Users\Taylor\Raydium-LP1
Test-Path .\setup_wizard.ps1
Test-Path .\run_scan.ps1
Test-Path .\scripts\scan_raydium_lps.py
```

If either line prints `False`, your folder does not have the scanner files yet.

### `py: The term 'py' is not recognized`

This means the Python launcher is not installed or not on PATH. Try plain `python`:

```powershell
python --version
python scripts\scan_raydium_lps.py --config config\settings.json
```

If `python --version` also fails, install Python 3 from <https://www.python.org/downloads/windows/>. During install, check **Add python.exe to PATH**, then open a new PowerShell window.

## Safety model

This project does **not** ask for a seed phrase or private key. Do not paste wallet secrets into config files, `.env`, PowerShell, chat, or GitHub.

The first production-data demo should only prove that live Raydium data can be fetched, normalized, filtered, and reported. A separate, explicit step is required before adding wallet signing or LP-opening logic.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
