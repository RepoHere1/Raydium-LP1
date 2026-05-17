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
    try {
        $cfg = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        if ($cfg.require_sell_route -eq $true) {
            Write-Host "[scan] WARNING: require_sell_route=true — Jupiter/Raydium probes per pool; scans are slow. Ctrl+C is normal if impatient." -ForegroundColor Yellow
            Write-Host "[scan] For fast TVL discovery use: .\scripts\START-HERE.ps1  (or run_tune_scan.ps1)" -ForegroundColor DarkYellow
        }
        $sort = [string]$cfg.pool_sort_field
        if ([string]::IsNullOrWhiteSpace($sort) -or $sort -match '^(apr|apr24h)$') {
            Write-Host "[scan] WARNING: pool_sort_field is empty or APR-sorted — page 1 is often dust TVL. Try pool_sort_field=liquidity in settings." -ForegroundColor Yellow
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
