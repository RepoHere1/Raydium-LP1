<#
.SYNOPSIS
  LIVE $1 CLMM open on a fixed pool using Trailing / Dynamic Skew Order + safeguards.

.DESCRIPTION
  Safeguards for this script (always on):
    - mode=live required
    - lp_open_pay_token_only (--force-pay-only): deposit SOL/USDC/USDT only
    - fee_guard_enabled (--force-fee-guard): blocks micro-deposits / fee-burn opens
    - pool verification + live_readiness_check via open_live_lp_cli
    - capped priority fees from settings

  Strategy: trailing_dynamic_skew (Dynamic Skew Order) with lp_skew_use_momentum.

  NOTE: $1 (~0.005-0.006 SOL) is often BELOW fee-guard minimums (rent ~0.04 SOL).
  Preview first; if blocked, raise -UsdAmount or use --UseMinDeposit.

.EXAMPLE
  .\scripts\export_keypair.ps1
  .\scripts\open_skew_1usd.ps1 -PreviewOnly

.EXAMPLE
  .\scripts\open_skew_1usd.ps1 -UsdAmount 1 -PreviewOnly

.EXAMPLE
  Live open (type nothing extra — signs on-chain):
  .\scripts\open_skew_1usd.ps1
#>
param(
    [string]$PoolId = "2LoAqKKfMtcu5azXuqyDY7wLsdXR632qMHtG5SF9wy2X",
    [double]$UsdAmount = 1.0,
    [double]$SolPriceUsd = 0,
    [switch]$PreviewOnly,
    [switch]$UseMinDeposit
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

if ($SolPriceUsd -le 0) {
    $envPrice = $env:SOL_USD_PRICE
    if ($envPrice -and [double]::TryParse($envPrice, [ref]$null)) {
        $SolPriceUsd = [double]$envPrice
    } else {
        $SolPriceUsd = 180.0
    }
}

$SolAmount = [math]::Round($UsdAmount / $SolPriceUsd, 6)

Write-Host ""
Write-Host "=== BUY `$1 Dynamic Skew (safeguarded LIVE open) ===" -ForegroundColor Cyan
Write-Host "  Pool:      $PoolId"
Write-Host "  Strategy:  trailing_dynamic_skew (Dynamic Skew Order)"
Write-Host "  Notional:  `$$UsdAmount USD -> $SolAmount SOL (@ `$$SolPriceUsd/SOL)"
Write-Host "  Safeguards: pay-token-only, fee-guard, verification, readiness"
Write-Host ""

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $pyExe = "py"; $pyArgs = @("-3") }
else { $pyExe = "python"; $pyArgs = @() }

$cliArgs = @(
    (Join-Path $RepoRoot "scripts\open_live_lp_cli.py"),
    $PoolId,
    "--strategy", "trailing_dynamic_skew",
    "--force-pay-only",
    "--force-fee-guard",
    "--sol-price", "$SolPriceUsd"
)
if ($UseMinDeposit) {
    $cliArgs += "--use-min-deposit"
} else {
    $cliArgs += @("--usd", "$UsdAmount")
}
if ($PreviewOnly) { $cliArgs += "--preview-only" }

& $pyExe @pyArgs @cliArgs
$exit = $LASTEXITCODE
if ($exit -ne 0) { exit $exit }

if (-not $PreviewOnly) {
    Write-Host ""
    Write-Host "Done. Check active_positions.json and dashboard LIVE trades." -ForegroundColor Green
}
