# Scanner loop + reports\dashboard.json + reload config each cycle (for the web UI).
# Window 1 in Windows Terminal:
#   cd C:\Users\Taylor\Raydium-LP1
#   .\scripts\run_scan_dashboard.ps1
# Optional: .\scripts\run_scan_dashboard.ps1 -WriteRejections -CheckRpc -Interval 120
param(
    [string]$Config = "config\settings.json",
    [int]$Interval = 60,
    [int]$ShowRejects = 0,
    [switch]$CheckRpc,
    [switch]$WriteReports,
    [switch]$WriteRejections,
    [switch]$SpawnWatcher
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$configPath = Join-Path $repo $Config
if (Test-Path -LiteralPath $configPath) {
    $rawCfg = Get-Content -LiteralPath $configPath -Raw -ErrorAction SilentlyContinue
    if ($rawCfg -match '<<<<<<<') {
        Write-Host "[scan] ERROR: $Config has git merge conflict markers — scanner cannot start." -ForegroundColor Red
        Write-Host "[scan] Fix: .\scripts\fix_pool_type.ps1 -Config $Config -ResetScanFilters" -ForegroundColor Yellow
        exit 2
    }
    try {
        $cfg = $rawCfg | ConvertFrom-Json
        if ($cfg.require_sell_route -eq $true) {
            Write-Host "[scan] WARNING: require_sell_route=true — Jupiter/Raydium probes per pool; scans are slow. Ctrl+C is normal if impatient." -ForegroundColor Yellow
            Write-Host "[scan] For fast TVL discovery use: .\scripts\START-HERE.ps1  (or run_tune_scan.ps1)" -ForegroundColor DarkYellow
        }
        $sort = [string]$cfg.pool_sort_field
        if ([string]::IsNullOrWhiteSpace($sort) -or $sort -match '^(apr|apr24h)$') {
            Write-Host "[scan] WARNING: pool_sort_field is empty or APR-sorted — page 1 is often dust TVL. Try pool_sort_field=liquidity in settings." -ForegroundColor Yellow
        }
        $poolType = [string]$cfg.pool_type
        if ([string]::IsNullOrWhiteSpace($poolType)) {
            Write-Host "[scan] ERROR: pool_type is blank in $Config — Raydium list API returns HTTP 500 (poolType=)." -ForegroundColor Red
            Write-Host "[scan] Repairing pool_type=all on disk …" -ForegroundColor Yellow
            $env:PYTHONPATH = "src"
            & py -3 -c "from pathlib import Path; from raydium_lp1.settings_io import repair_settings_file_if_needed; repair_settings_file_if_needed(Path(r'$Config'))" 2>$null
            if ($LASTEXITCODE -ne 0) {
                & python -c "from pathlib import Path; from raydium_lp1.settings_io import repair_settings_file_if_needed; repair_settings_file_if_needed(Path(r'$Config'))"
            }
            Write-Host "[scan] Done. Restart scanner if it was already running." -ForegroundColor Green
        }
    } catch {
        # non-fatal; scanner will load config
    }
}
& (Join-Path $here "run_scan.ps1") `
    -Config $Config `
    -Loop `
    -Interval $Interval `
    -ShowRejects $ShowRejects `
    -Dashboard `
    -ReloadConfigEachScan `
    -CheckRpc:$CheckRpc `
    -WriteReports:$WriteReports `
    -WriteRejections:$WriteRejections `
    -SpawnWatcher:$SpawnWatcher `
    @args
exit $LASTEXITCODE
