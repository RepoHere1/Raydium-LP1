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
