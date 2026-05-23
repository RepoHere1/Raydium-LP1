# Fast candidate discovery — TVL-sorted, no Jupiter route probes, no on-chain verify.
# Use this when APR-sorted scans show 100% [REJ] dust and feel "broken".
#
#   cd C:\Users\Taylor\Raydium-LP1
#   .\scripts\run_tune_scan.ps1
param(
    [int]$Interval = 60,
    [int]$ShowRejects = 0
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Join-Path (Split-Path -Parent $here) "config\settings.tune.json"

Write-Host ""
Write-Host "=== TUNE SCAN (liquidity sort, no route probes) ===" -ForegroundColor Cyan
Write-Host "Config: $config" -ForegroundColor DarkGray
Write-Host "Do NOT paste lines that start with WHERE, CHECK, or LOOK into PowerShell." -ForegroundColor Yellow
Write-Host ""

& (Join-Path $here "run_scan_dashboard.ps1") -Config $config -Interval $Interval -ShowRejects $ShowRejects @args
exit $LASTEXITCODE
