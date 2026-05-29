<#
.SYNOPSIS
  LIVE ~$0.50 CLMM open — Standard Full Range Order, pay-token-only.

.EXAMPLE
  .\scripts\open_fullrange_50c.ps1 -PreviewOnly
  .\scripts\open_fullrange_50c.ps1 -PoolId "2LoAqKKfMtcu5azXuqyDY7wLsdXR632qMHtG5SF9wy2X"
#>
param(
    [string]$PoolId = "2LoAqKKfMtcu5azXuqyDY7wLsdXR632qMHtG5SF9wy2X",
    [double]$UsdAmount = 0.50,
    [double]$SolPriceUsd = 0,
    [switch]$PreviewOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

if ($SolPriceUsd -le 0) {
    $ep = $env:SOL_USD_PRICE
    if ($ep -and [double]::TryParse($ep, [ref]$null)) { $SolPriceUsd = [double]$ep }
    else { $SolPriceUsd = 180.0 }
}

Write-Host ""
Write-Host "=== BUY ~`$$UsdAmount Full Range (Standard Full Range Order) ===" -ForegroundColor Cyan
Write-Host "  Pool:     $PoolId"
Write-Host "  Strategy: standard_full_range"
Write-Host ""

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $pyExe = "py"; $pyArgs = @("-3") }
else { $pyExe = "python"; $pyArgs = @() }

$cliArgs = @(
    (Join-Path $RepoRoot "scripts\open_live_lp_cli.py"),
    $PoolId,
    "--usd", "$UsdAmount",
    "--strategy", "standard_full_range",
    "--force-pay-only",
    "--sol-price", "$SolPriceUsd"
)
if ($PreviewOnly) { $cliArgs += "--preview-only" }

& $pyExe @pyArgs @cliArgs
exit $LASTEXITCODE
