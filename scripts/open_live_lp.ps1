<#
.SYNOPSIS
  Open one small CLMM LP on-chain (LIVE) and append active_positions.json.

.PARAMETER PoolId
  Raydium pool id from reports/latest.json. Default: top candidate.

.PARAMETER SolAmount
  SOL to deposit (human). Default 0.005 (~75c at ~$150/SOL; CLMM min often needs >=0.005).

.PARAMETER UsdAmount
  If set (>0), overrides SolAmount using SolPriceUsd or env SOL_USD_PRICE.

.PARAMETER SolPriceUsd
  SOL/USD for UsdAmount sizing (0 = use env or 180).

.EXAMPLE
  .\scripts\export_keypair.ps1
  .\scripts\open_live_lp.ps1

.EXAMPLE
  .\scripts\open_live_lp.ps1 -PoolId "BSPFA8d9qeZdsTubmS6FvriYadx2mzoi6jesauD6hi4e" -SolAmount 0.005

.EXAMPLE
  ~25 cents at $180/SOL:
  .\scripts\open_live_lp.ps1 -PoolId "BSPFA8d9qeZdsTubmS6FvriYadx2mzoi6jesauD6hi4e" -UsdAmount 0.25
#>
param(
    [string]$PoolId = "",
    [double]$SolAmount = 0.005,
    [double]$UsdAmount = 0,
    [double]$SolPriceUsd = 0
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction Stop; $pyExe = "py"; $pyArgs = @("-3") }
else { $pyExe = "python"; $pyArgs = @() }

Write-Host "Candidates in reports/latest.json:" -ForegroundColor Cyan
& $pyExe @pyArgs (Join-Path $RepoRoot "scripts\list_candidates.py")

if (-not $PoolId) {
    $ans = Read-Host "Pool id (Enter = top candidate)"
    if ($ans.Trim()) { $PoolId = $ans.Trim() }
}

if ($UsdAmount -gt 0) {
    if ($SolPriceUsd -le 0) {
        $ep = $env:SOL_USD_PRICE
        if ($ep -and [double]::TryParse($ep, [ref]$null)) { $SolPriceUsd = [double]$ep }
        else { $SolPriceUsd = 180.0 }
    }
    $SolAmount = [math]::Round($UsdAmount / $SolPriceUsd, 6)
    Write-Host "UsdAmount `$$UsdAmount @ `$$SolPriceUsd/SOL -> $SolAmount SOL (pay-token-only rules)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Opening LIVE CLMM with ${SolAmount} SOL ..." -ForegroundColor Yellow
& $pyExe @pyArgs (Join-Path $RepoRoot "scripts\open_live_lp_cli.py") $PoolId --sol "$SolAmount"
$exit = $LASTEXITCODE
if ($exit -ne 0) { exit $exit }

Write-Host ""
Write-Host "Refresh dashboard data:" -ForegroundColor Cyan
Write-Host "  .\scripts\run_scan.ps1 -WriteReports   # or Run scan now in browser" -ForegroundColor DarkGray
Write-Host "  Get-Content .\active_positions.json" -ForegroundColor DarkGray
