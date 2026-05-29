<#
.SYNOPSIS
  LIVE CLMM open for pool 6dquhnENWL2MeV1VModn4GeERJjHzwuHedaqZoCT3WEq, pay-token-only (SOL/USDC/USDT).

.DESCRIPTION
  Fee guard blocks ~25¢ opens: CLMM rent (~0.04 SOL) dominates tiny deposits.
  Default uses min_clmm_deposit_sol from settings (~0.008 SOL). Pass -UsdAmount only if above minimum.

.EXAMPLE
  .\scripts\export_keypair.ps1
  .\scripts\open_proof_25c.ps1

.EXAMPLE
  .\scripts\open_proof_25c.ps1 -PoolId "YOUR_POOL_ID" -UsdAmount 0.25

.EXAMPLE
  Preview only (no tx):
  .\scripts\open_proof_25c.ps1 -PreviewOnly
#>
param(
    [string]$PoolId = "6dquhnENWL2MeV1VModn4GeERJjHzwuHedaqZoCT3WEq",
    [double]$UsdAmount = 0,
    [double]$SolPriceUsd = 0,
    [switch]$PreviewOnly
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

$useMin = ($UsdAmount -le 0)
if ($useMin) {
    Write-Host "  Deposit:  min_clmm_deposit_sol from settings (fee guard — not 25c)" -ForegroundColor Yellow
} else {
    $SolAmount = [math]::Round($UsdAmount / $SolPriceUsd, 6)
    Write-Host "  Notional: `$$UsdAmount USD  ->  $SolAmount SOL  (@ `$$SolPriceUsd / SOL)"
}

Write-Host ""
Write-Host "=== BUY POOL (pay-token-only + fee guard) ===" -ForegroundColor Cyan
Write-Host "  Pool:     $PoolId"
Write-Host "  Rules:    lp_open_pay_token_only — deposit SOL/USDC/USDT only, not alt leg"
Write-Host ""

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $pyExe = "py"; $pyArgs = @("-3") }
else { $pyExe = "python"; $pyArgs = @() }

$cliArgs = @(
    (Join-Path $RepoRoot "scripts\open_live_lp_cli.py"),
    $PoolId,
    "--sol-price", "$SolPriceUsd"
)
if ($useMin) { $cliArgs += "--use-min-deposit" }
else { $cliArgs += @("--usd", "$UsdAmount") }
if ($PreviewOnly) { $cliArgs += "--preview-only" }
$cliArgs += "--force-pay-only"

& $pyExe @pyArgs @cliArgs
$exit = $LASTEXITCODE
if ($exit -ne 0) { exit $exit }

if (-not $PreviewOnly) {
    Write-Host ""
    Write-Host "Done. Check active_positions.json and dashboard LIVE trades." -ForegroundColor Green
}
