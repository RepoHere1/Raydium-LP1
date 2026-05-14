param(
    [string]$ConfigPath = "config\settings.json",
    [string]$EnvPath = ".env"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

function Ask-WithDefault {
    param([string]$Question, [string]$Default)
    $answer = Read-Host "$Question [$Default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Ask-YesNo {
    param([string]$Question, [bool]$DefaultYes = $true)
    $defaultText = if ($DefaultYes) { "Y" } else { "N" }
    $answer = Read-Host "$Question (Y/N) [$defaultText]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $DefaultYes }
    return $answer.Trim().ToLowerInvariant().StartsWith("y")
}

Write-Host ""
Write-Host "Raydium-LP1 setup wizard" -ForegroundColor Cyan
Write-Host "This creates your local config\settings.json and .env files."
Write-Host "Your .env can contain private RPC/API-key URLs and is ignored by Git."
Write-Host ""

$minApr = [double](Ask-WithDefault "Minimum APR percent to flag. You said 999.99, and you can change it later" "999.99")
$minLiquidity = [double](Ask-WithDefault "Minimum pool liquidity/TVL in USD" "1000")
$minVolume = [double](Ask-WithDefault "Minimum 24h volume in USD" "100")
$maxPosition = [double](Ask-WithDefault "Future max position size in USD; scanner is still dry-run only" "25")
$quotesRaw = Ask-WithDefault "Allowed quote symbols, comma-separated" "SOL,USDC,USDT"
$pageSize = [int](Ask-WithDefault "Raydium page size. Raydium docs allow up to 1000" "100")
$pages = [int](Ask-WithDefault "How many Raydium pages to scan per run" "1")
$raydiumApiBase = Ask-WithDefault "Raydium live API base" "https://api-v3.raydium.io"
$primaryRpc = Ask-WithDefault "Primary Solana RPC URL. Public default is OK; paste Helius/Chainstack/etc if you want" "https://api.mainnet-beta.solana.com"

$fallbacks = New-Object System.Collections.Generic.List[string]
$fallbacks.Add("https://solana-rpc.publicnode.com")
$fallbacks.Add("https://solana.drpc.org")
Write-Host ""
Write-Host "Add backup RPC URLs. Paste one URL at a time. Press Enter on a blank line when done."
while ($true) {
    $rpc = Read-Host "Backup RPC URL"
    if ([string]::IsNullOrWhiteSpace($rpc)) { break }
    $fallbacks.Add($rpc.Trim())
}

$allowedQuotes = $quotesRaw.Split(",") | ForEach-Object { $_.Trim().ToUpperInvariant() } | Where-Object { $_ }
$config = [ordered]@{
    dry_run = $true
    min_apr = $minApr
    apr_field = "apr24h"
    raydium_api_base = $raydiumApiBase
    pool_type = "all"
    sort_type = "desc"
    page_size = $pageSize
    pages = $pages
    min_liquidity_usd = $minLiquidity
    min_volume_24h_usd = $minVolume
    max_position_usd = $maxPosition
    allowed_quote_symbols = @($allowedQuotes)
    blocked_token_symbols = @()
    blocked_mints = @()
    require_pool_id = $true
    solana_rpc_urls = @()
}

$configDir = Split-Path -Parent $ConfigPath
if ($configDir -and -not (Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir | Out-Null }
$config | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigPath -Encoding UTF8

$allFallbacks = ($fallbacks | Where-Object { $_ -and $_ -ne $primaryRpc }) -join ","
@(
    "# Raydium-LP1 local live data sources. This file is ignored by Git.",
    "RAYDIUM_API_BASE=$raydiumApiBase",
    "SOLANA_RPC_URL=$primaryRpc",
    "SOLANA_RPC_URLS=$allFallbacks"
) | Set-Content -Path $EnvPath -Encoding UTF8

Write-Host ""
Write-Host "Created $ConfigPath with min_apr=$minApr" -ForegroundColor Green
Write-Host "Created $EnvPath with your live RPC/API URLs" -ForegroundColor Green
Write-Host ""
Write-Host "Next paste/run:" -ForegroundColor Cyan
Write-Host ".\scripts\doctor.ps1"
Write-Host ".\scripts\run_scan.ps1 -CheckRpc -WriteReports"

if (Ask-YesNo "Run doctor check now?" $true) {
    & "$ScriptDir\doctor.ps1"
}
