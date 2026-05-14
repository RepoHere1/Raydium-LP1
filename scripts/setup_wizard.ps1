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

Write-Host ""
Write-Host "Strategy presets (you can pick a profile and skip the manual numbers):"
Write-Host "  conservative   APR>=  50%  TVL>=`$50000  Vol>=`$10000   - boring, safer pairs"
Write-Host "  moderate       APR>= 200%  TVL>=`$10000  Vol>=`$1000    - mid-cap yield"
Write-Host "  aggressive     APR>= 777%  TVL>=`$500    Vol>=`$100     - high APR hunting"
Write-Host "  degen          APR>= 500%  TVL>=`$200    Vol>=`$50      - anything that pumps"
Write-Host "  custom         keep manual values you enter below"
$strategy = (Ask-WithDefault "Strategy" "custom").ToLowerInvariant()

switch ($strategy) {
    "conservative" { $minAprDefault = 50;  $minLiqDefault = 50000; $minVolDefault = 10000 }
    "moderate"     { $minAprDefault = 200; $minLiqDefault = 10000; $minVolDefault = 1000  }
    "aggressive"   { $minAprDefault = 777; $minLiqDefault = 500;   $minVolDefault = 100   }
    "degen"        { $minAprDefault = 500; $minLiqDefault = 200;   $minVolDefault = 50    }
    default        { $strategy = "custom"; $minAprDefault = 999.99; $minLiqDefault = 1000; $minVolDefault = 100 }
}

$minApr = [double](Ask-WithDefault "Minimum APR percent to flag" "$minAprDefault")
$minLiquidity = [double](Ask-WithDefault "Minimum pool liquidity/TVL in USD" "$minLiqDefault")
$minVolume = [double](Ask-WithDefault "Minimum 24h volume in USD" "$minVolDefault")
$maxPosition = [double](Ask-WithDefault "Future max position size in USD; scanner is still dry-run only" "25")
$quotesRaw = Ask-WithDefault "Allowed quote symbols, comma-separated" "SOL,USDC,USDT"
$pageSize = [int](Ask-WithDefault "Raydium page size. Raydium docs allow up to 1000" "100")
if ($pageSize -lt 10) { $pageSize = 10 }
if ($pageSize -gt 1000) {
    Write-Host "  page size $pageSize exceeds Raydium's documented max; clamping to 1000." -ForegroundColor Yellow
    $pageSize = 1000
}
$pages = [int](Ask-WithDefault "How many Raydium pages to scan per run (1-50; one scan-cycle hits this many HTTP requests)" "1")
if ($pages -lt 1) { $pages = 1 }
if ($pages -gt 50) {
    Write-Host "  pages=$pages would issue $pages back-to-back HTTP calls and is almost certainly a typo." -ForegroundColor Yellow
    Write-Host "  clamping to 50. Raise it again later by editing config\settings.json if you really mean it." -ForegroundColor Yellow
    $pages = 50
}
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
    strategy = $strategy
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
