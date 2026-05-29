<#
.SYNOPSIS
  Find Raydium CLMM pool for a mint, then open ~$0.25 LPs (Centered Tight + Full Range).

.PARAMETER Mint
  Token mint (default BABYTROLL pump mint).

.EXAMPLE
  .\scripts\open_babytroll_dual_25c.ps1 -PreviewOnly
#>
param(
    [string]$Mint = "6qdzMx4c9rL2X3Ns3SwZ8uEo4zReDPjdXpAEmpo7pump",
    [string]$PoolId = "",
    [double]$UsdAmount = 0.25,
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

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $pyExe = "py"; $pyArgs = @("-3") }
else { $pyExe = "python"; $pyArgs = @() }

if (-not $PoolId) {
    Write-Host "Finding Raydium CLMM pools for mint $Mint ..." -ForegroundColor Cyan
    $find = & $pyExe @pyArgs (Join-Path $RepoRoot "scripts\find_mint_pool.py") $Mint 2>&1 | Out-String
    Write-Host $find
    $json = ($find -split "`n" | Where-Object { $_ -match '^\{' } | Select-Object -First 1)
    if (-not $json) {
        $json = ($find | Select-String -Pattern '\{[\s\S]*\}' -AllMatches).Matches[0].Value
    }
    try {
        $parsed = $json | ConvertFrom-Json
        $PoolId = $parsed.pools[0].pool_id
    } catch {
        Write-Host "Could not parse pool finder output." -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Pool: $PoolId  |  ~`$$UsdAmount per leg  |  pay-token-only" -ForegroundColor Yellow
Write-Host "WARNING: BABYTROLL Raydium CLMM pools are dust TVL (~`$6). PumpSwap has real liq; this is Raydium-only." -ForegroundColor DarkYellow
Write-Host ""

$common = @(
    $PoolId,
    "--usd", "$UsdAmount",
    "--force-pay-only",
    "--sol-price", "$SolPriceUsd"
)
if ($PreviewOnly) { $common += "--preview-only" }

foreach ($leg in @(
    @{ Name = "Centered Tight"; Strategy = "centered_tight_range" },
    @{ Name = "Full Range"; Strategy = "standard_full_range" }
)) {
    Write-Host "=== $($leg.Name) ($($leg.Strategy)) ===" -ForegroundColor Cyan
    & $pyExe @pyArgs @(
        (Join-Path $RepoRoot "scripts\open_live_lp_cli.py")
    ) + $common + @("--strategy", $leg.Strategy)
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
}

if (-not $PreviewOnly) {
    Write-Host "Both legs done. See active_positions.json" -ForegroundColor Green
}
