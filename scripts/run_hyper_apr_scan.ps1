# High-APR discovery — liquid Raydium pools, shortlist ranked by day.apr (matches raydium.io %).
#
#   cd C:\Users\Taylor\Raydium-LP1
#   .\scripts\run_hyper_apr_scan.ps1
param(
    [int]$Interval = 60,
    [int]$ShowRejects = 0
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Join-Path (Split-Path -Parent $here) "config\settings.hyper_apr.json"

Write-Host ""
Write-Host "=== HYPER-APR SCAN (TVL-ranked pages, APR-sorted shortlist) ===" -ForegroundColor Cyan
Write-Host "Config: $config" -ForegroundColor DarkGray
Write-Host "APR = Raydium pool.day.apr (same as the liquidity table on raydium.io)." -ForegroundColor DarkGray
Write-Host "Do NOT paste lines that start with WHERE, CHECK, or LOOK into PowerShell." -ForegroundColor Yellow
Write-Host ""

& (Join-Path $here "run_scan_dashboard.ps1") -Config $config -Interval $Interval -ShowRejects $ShowRejects @args
exit $LASTEXITCODE
