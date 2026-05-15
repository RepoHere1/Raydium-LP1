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

function Read-EnvDefaults {
    param([string]$Path)
    $result = @{ "RAYDIUM_API_BASE" = $null; "SOLANA_RPC_URL" = $null; "SOLANA_RPC_URLS" = $null }
    if (-not (Test-Path $Path)) { return $result }
    foreach ($line in (Get-Content $Path -Encoding UTF8)) {
        $line = $line.Trim()
        if ($line -eq "" -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
        $idx = $line.IndexOf("=")
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim().Trim("'", '"')
        if ($result.ContainsKey($key)) { $result[$key] = $value }
    }
    return $result
}

function Read-ConfigDefaults {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        return (Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        Write-Host "  (could not parse existing $Path; ignoring saved values)" -ForegroundColor Yellow
        return $null
    }
}

# Pre-load anything the user already had so the prompts use it as defaults.
$envDefaults = Read-EnvDefaults -Path $EnvPath
$configDefaults = Read-ConfigDefaults -Path $ConfigPath

function Get-Default {
    param($Object, [string]$PropertyName, $Fallback)
    if ($null -eq $Object) { return $Fallback }
    $prop = $Object.PSObject.Properties[$PropertyName]
    if ($null -eq $prop -or $null -eq $prop.Value -or "$($prop.Value)".Trim() -eq "") {
        return $Fallback
    }
    return $prop.Value
}

Write-Host ""
Write-Host "Raydium-LP1 setup wizard" -ForegroundColor Cyan
Write-Host "This creates your local config\settings.json and .env files."
Write-Host "Your .env can contain private RPC/API-key URLs and is ignored by Git."
Write-Host ""

if ($null -ne $configDefaults -or $null -ne $envDefaults["SOLANA_RPC_URL"]) {
    Write-Host "Found existing settings; using them as defaults. Press Enter to keep, or type a new value." -ForegroundColor DarkGray
    Write-Host ""
}

Write-Host "Strategy presets (you can pick a profile and skip the manual numbers):"
Write-Host "  conservative   APR>=  50%  TVL>=`$50000  Vol>=`$10000   - boring, safer pairs"
Write-Host "  moderate       APR>= 200%  TVL>=`$10000  Vol>=`$1000    - mid-cap yield"
Write-Host "  aggressive     APR>= 777%  TVL>=`$500    Vol>=`$100     - high APR hunting"
Write-Host "  degen          APR>= 500%  TVL>=`$200    Vol>=`$50      - anything that pumps"
Write-Host "  momentum       APR>= 300%  TVL>=`$5000  Vol>=`$500      - real TVL + buyer flow (fee-rush LP)"
Write-Host "  custom         keep manual values you enter below"
$savedStrategy = "$(Get-Default $configDefaults 'strategy' 'custom')"
$strategy = (Ask-WithDefault "Strategy" $savedStrategy).ToLowerInvariant()

switch ($strategy) {
    "conservative" { $minAprDefault = 50;  $minLiqDefault = 50000; $minVolDefault = 10000 }
    "moderate"     { $minAprDefault = 200; $minLiqDefault = 10000; $minVolDefault = 1000  }
    "aggressive"   { $minAprDefault = 777; $minLiqDefault = 500;   $minVolDefault = 100   }
    "degen"        { $minAprDefault = 500; $minLiqDefault = 200;   $minVolDefault = 50    }
    "momentum"     { $minAprDefault = 300; $minLiqDefault = 5000;  $minVolDefault = 500   }
    "fee_rush"     { $strategy = "momentum"; $minAprDefault = 300; $minLiqDefault = 5000; $minVolDefault = 500 }
    default        { $strategy = "custom"; $minAprDefault = 999.99; $minLiqDefault = 1000; $minVolDefault = 100 }
}
# Remembered values still win over preset numbers when present.
$minAprDefault       = Get-Default $configDefaults "min_apr"           $minAprDefault
$minLiqDefault       = Get-Default $configDefaults "min_liquidity_usd" $minLiqDefault
$minVolDefault       = Get-Default $configDefaults "min_volume_24h_usd" $minVolDefault
$maxPositionDefault  = Get-Default $configDefaults "max_position_usd"  25
$pageSizeDefault     = Get-Default $configDefaults "page_size"         100
$pagesDefault        = Get-Default $configDefaults "pages"             1

$minApr = [double](Ask-WithDefault "Minimum APR percent to flag" "$minAprDefault")
Write-Host ""
Write-Host "TVL (liquidity) = real USD in the pool you would LP into. Dust pools show fake APR on `$0.01 TVL." -ForegroundColor DarkGray
$minLiquidity = [double](Ask-WithDefault "Minimum pool TVL / liquidity in USD (actionable LP floor)" "$minLiqDefault")
$hardTvlDefault = Get-Default $configDefaults "hard_exit_min_tvl_usd" 0
$hardTvl = [double](Ask-WithDefault "Hard exit-safety TVL floor (0=off; momentum preset default 1000)" "$hardTvlDefault")
$minVolume = [double](Ask-WithDefault "Minimum 24h volume in USD" "$minVolDefault")
$maxPosition = [double](Ask-WithDefault "Future max position size in USD; scanner is still dry-run only" "$maxPositionDefault")

# Allowed-quotes: prefer the previously-saved array, else fall back to wide default.
if ($null -ne $configDefaults -and $configDefaults.PSObject.Properties["allowed_quote_symbols"]) {
    $quotesDefault = ($configDefaults.allowed_quote_symbols -join ",")
} else { $quotesDefault = "SOL,USDC,USDT" }
$quotesRaw = Ask-WithDefault "Allowed quote symbols, comma-separated" $quotesDefault

$pageSize = [int](Ask-WithDefault "Raydium page size. Raydium docs allow up to 1000" "$pageSizeDefault")
if ($pageSize -lt 10) { $pageSize = 10 }
if ($pageSize -gt 1000) {
    Write-Host "  page size $pageSize exceeds Raydium's documented max; clamping to 1000." -ForegroundColor Yellow
    $pageSize = 1000
}
$pages = [int](Ask-WithDefault "How many Raydium pages to scan per run (1-50; one scan-cycle hits this many HTTP requests)" "$pagesDefault")
if ($pages -lt 1) { $pages = 1 }
if ($pages -gt 50) {
    Write-Host "  pages=$pages would issue $pages back-to-back HTTP calls and is almost certainly a typo." -ForegroundColor Yellow
    Write-Host "  clamping to 50. Raise it again later by editing config\settings.json if you really mean it." -ForegroundColor Yellow
    $pages = 50
}

Write-Host ""
Write-Host "Raydium page ordering (pool_sort_field): APR-sorted pages favor micro-TVL hype pools. Use volume24h (or liquidity) to scan a friendlier slice." -ForegroundColor DarkGray
$poolSortSaved = "$(Get-Default $configDefaults 'pool_sort_field' '')".Trim()
$poolSortField = (Ask-WithDefault "pool_sort_field (blank = same as APR field; try volume24h)" $poolSortSaved).Trim()

$raydiumApiBaseDefault = if ($envDefaults["RAYDIUM_API_BASE"]) { $envDefaults["RAYDIUM_API_BASE"] } else { "https://api-v3.raydium.io" }
$raydiumApiBase = Ask-WithDefault "Raydium live API base" $raydiumApiBaseDefault

$primaryRpcDefault = if ($envDefaults["SOLANA_RPC_URL"]) { $envDefaults["SOLANA_RPC_URL"] } else { "https://api.mainnet-beta.solana.com" }
$primaryRpc = Ask-WithDefault "Primary Solana RPC URL. Public default is OK; paste Helius/Chainstack/etc if you want" $primaryRpcDefault

$fallbacks = New-Object System.Collections.Generic.List[string]
if ($envDefaults["SOLANA_RPC_URLS"]) {
    foreach ($entry in $envDefaults["SOLANA_RPC_URLS"].Split(",")) {
        $entry = $entry.Trim()
        if ($entry -and $entry -ne $primaryRpc) { $fallbacks.Add($entry) }
    }
}
if ($fallbacks.Count -eq 0) {
    $fallbacks.Add("https://solana-rpc.publicnode.com")
    $fallbacks.Add("https://solana.drpc.org")
}

Write-Host ""
Write-Host "Backup RPC URLs already saved:" -ForegroundColor DarkGray
foreach ($entry in $fallbacks) { Write-Host "  - $entry" -ForegroundColor DarkGray }
Write-Host "Press Enter to keep all of them, type 'clear' to drop them, or paste extras one at a time."
$clearedThisRun = $false
while ($true) {
    $rpc = Read-Host "Add backup RPC URL (Enter to finish)"
    if ([string]::IsNullOrWhiteSpace($rpc)) { break }
    $rpcTrim = $rpc.Trim()
    if ($rpcTrim.ToLowerInvariant() -eq "clear") {
        $fallbacks.Clear()
        $clearedThisRun = $true
        Write-Host "  cleared." -ForegroundColor Yellow
        continue
    }
    if (-not $fallbacks.Contains($rpcTrim)) { $fallbacks.Add($rpcTrim) }
}

$allowedQuotes = $quotesRaw.Split(",") | ForEach-Object { $_.Trim().ToUpperInvariant() } | Where-Object { $_ }

Write-Host ""
Write-Host "Momentum / fee-rush (ranks pools by live vol/TVL + acceleration; suggests when to exit):" -ForegroundColor Cyan
$momentumDefault = ($strategy -eq "momentum") -or (Get-Default $configDefaults "momentum_enabled" $false)
$momentumEnabled = Ask-YesNo "Enable momentum scoring on candidates?" $momentumDefault
$momScoreDefault = Get-Default $configDefaults "min_momentum_score" 50
$momScore = [double](Ask-WithDefault "Minimum momentum score 0-100 (only hard-rejects if you enable require below)" "$momScoreDefault")
$requireMomDefault = Get-Default $configDefaults "require_momentum_score" $false
$requireMom = Ask-YesNo "Hard-reject pools below min momentum score?" $requireMomDefault
$holdDefault = Get-Default $configDefaults "momentum_hold_hours" 24
Write-Host "  Hold bias: 24 = ~1 day fee-rush, 168 = ~1 week"
$holdHours = [double](Ask-WithDefault "Momentum hold bias (hours)" "$holdDefault")

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
    pool_sort_field = $poolSortField
    min_liquidity_usd = $minLiquidity
    hard_exit_min_tvl_usd = $hardTvl
    min_volume_24h_usd = $minVolume
    max_position_usd = $maxPosition
    momentum_enabled = $momentumEnabled
    min_momentum_score = $momScore
    require_momentum_score = $requireMom
    momentum_hold_hours = $holdHours
    momentum_min_volume_tvl_ratio = [double](Get-Default $configDefaults "momentum_min_volume_tvl_ratio" 0.5)
    momentum_sweet_min_pool_age_hours = [double](Get-Default $configDefaults "momentum_sweet_min_pool_age_hours" 6)
    momentum_sweet_max_pool_age_hours = [double](Get-Default $configDefaults "momentum_sweet_max_pool_age_hours" 168)
    momentum_min_tvl_usd = $minLiquidity
    momentum_top_hot = [int](Get-Default $configDefaults "momentum_top_hot" 25)
    momentum_detective_enabled = $momentumEnabled
    momentum_probe_market_lists = $momentumEnabled
    sort_candidates_by_momentum = $true
    allowed_quote_symbols = @($allowedQuotes)
    blocked_token_symbols = @()
    blocked_mints = @()
    require_pool_id = $true
    solana_rpc_urls = @(@($primaryRpc) + $fallbacks | Where-Object { $_ } | Select-Object -Unique)
}

$configDir = Split-Path -Parent $ConfigPath
if ($configDir -and -not (Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir | Out-Null }

$pythonExe = "python"
$pythonPrefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
    $pythonPrefix = @("-3")
}
$tmpConfig = [System.IO.Path]::GetTempFileName() + ".json"
try {
    $config | ConvertTo-Json -Depth 8 | Set-Content -Path $tmpConfig -Encoding UTF8
    $env:PYTHONPATH = "src"
    & $pythonExe @pythonPrefix -m raydium_lp1.settings_sync --normalize $tmpConfig --output $ConfigPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not write valid JSON to $ConfigPath. See error above."
    }
} finally {
    Remove-Item -LiteralPath $tmpConfig -ErrorAction SilentlyContinue
}

$allFallbacks = ($fallbacks | Where-Object { $_ -and $_ -ne $primaryRpc }) -join ","
@(
    "# Raydium-LP1 local live data sources. This file is ignored by Git.",
    "RAYDIUM_API_BASE=$raydiumApiBase",
    "SOLANA_RPC_URL=$primaryRpc",
    "SOLANA_RPC_URLS=$allFallbacks"
) | Set-Content -Path $EnvPath -Encoding UTF8

Write-Host ""
Write-Host "Created $ConfigPath with min_apr=$minApr, strategy=$strategy" -ForegroundColor Green
Write-Host "Saved $($fallbacks.Count + 1) RPC URL(s) to both $ConfigPath and $EnvPath" -ForegroundColor Green
Write-Host ""
Write-Host "Next paste/run:" -ForegroundColor Cyan
Write-Host ".\scripts\doctor.ps1"
Write-Host ".\scripts\run_scan.ps1 -CheckRpc -WriteReports"

if (Ask-YesNo "Run doctor check now?" $true) {
    & "$ScriptDir\doctor.ps1"
}
