param(
    [string]$ConfigPath = "config\settings.json",
    [string]$EnvPath = ".env"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Host "Could not parse existing $Path (will use defaults): $_" -ForegroundColor Yellow
        return $null
    }
}

function Read-EnvFile {
    param([string]$Path)
    $bag = @{}
    if (-not (Test-Path $Path)) { return $bag }
    Get-Content -Path $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $eq = $line.IndexOf("=")
            $key = $line.Substring(0, $eq).Trim()
            $value = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
            if ($key) { $bag[$key] = $value }
        }
    }
    return $bag
}

function Coalesce-Default {
    param($Value, $Fallback)
    if ($null -eq $Value) { return [string]$Fallback }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return [string]$Fallback }
    return $text
}

function Coalesce-Bool {
    param($Value, [bool]$Fallback)
    if ($null -eq $Value) { return $Fallback }
    if ($Value -is [bool]) { return [bool]$Value }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $Fallback }
    switch ($text.Trim().ToLowerInvariant()) {
        'true'  { return $true }
        '1'     { return $true }
        'yes'   { return $true }
        'y'     { return $true }
        'false' { return $false }
        '0'     { return $false }
        'no'    { return $false }
        'n'     { return $false }
        default { return $Fallback }
    }
}

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

function Get-Property {
    param($Source, [string]$Name)
    if ($null -eq $Source) { return $null }
    if ($Source -is [System.Management.Automation.PSCustomObject]) {
        if ($Source.PSObject.Properties.Name -contains $Name) { return $Source.$Name }
        return $null
    }
    try { return $Source.$Name } catch { return $null }
}

Write-Host ""
Write-Host "Raydium-LP1 setup wizard" -ForegroundColor Cyan
Write-Host "Your previous answers (if any) are shown in [brackets] and used if you press Enter."
Write-Host "Your .env can contain private RPC/API-key URLs and is ignored by Git."
Write-Host ""

$existing = Read-JsonFile $ConfigPath
$existingEnv = Read-EnvFile $EnvPath

$survival = Get-Property $existing 'survival_runway'
$quoteOnly = Get-Property $existing 'quote_only_entry'
$honeypot = Get-Property $existing 'honeypot_guard'
$poolAge = Get-Property $existing 'pool_age_guard'
$mintAuth = Get-Property $existing 'mint_authority_guard'
$lpLock = Get-Property $existing 'lp_lock_guard'
$priceImpact = Get-Property $existing 'price_impact_guard'
$feeFloor = Get-Property $existing 'fee_apr_floor'
$rpcGate = Get-Property $existing 'rpc_health_gate'

$minApr = [double](Ask-WithDefault "Minimum APR percent to flag" (Coalesce-Default (Get-Property $existing 'min_apr') "999.99"))
$minLiquidity = [double](Ask-WithDefault "Minimum pool liquidity/TVL in USD" (Coalesce-Default (Get-Property $existing 'min_liquidity_usd') "1000"))
$minVolume = [double](Ask-WithDefault "Minimum 24h volume in USD" (Coalesce-Default (Get-Property $existing 'min_volume_24h_usd') "100"))
$maxPosition = [double](Ask-WithDefault "Future max position size in USD; scanner is still dry-run only" (Coalesce-Default (Get-Property $existing 'max_position_usd') "25"))

$existingQuotes = Get-Property $existing 'allowed_quote_symbols'
if ($null -ne $existingQuotes) {
    $quotesDefault = ($existingQuotes | ForEach-Object { [string]$_ }) -join ","
} else {
    $quotesDefault = "SOL,USDC,USDT,USD1"
}
$quotesRaw = Ask-WithDefault "Allowed quote symbols, comma-separated" $quotesDefault

$pageSize = [int](Ask-WithDefault "Raydium page size (Raydium docs allow up to 1000)" (Coalesce-Default (Get-Property $existing 'page_size') "100"))
$pages = [int](Ask-WithDefault "How many Raydium pages to scan per run" (Coalesce-Default (Get-Property $existing 'pages') "1"))
$raydiumApiBase = Ask-WithDefault "Raydium live API base" (Coalesce-Default (Coalesce-Default (Get-Property $existing 'raydium_api_base') $existingEnv['RAYDIUM_API_BASE']) "https://api-v3.raydium.io")

$primaryRpcDefault = Coalesce-Default $existingEnv['SOLANA_RPC_URL'] "https://api.mainnet-beta.solana.com"
$primaryRpc = Ask-WithDefault "Primary Solana RPC URL (paste Helius/Chainstack/etc if you have one)" $primaryRpcDefault

Write-Host ""
Write-Host "survival_runway: 'will this pool still be alive in 3-7 days?'" -ForegroundColor Cyan
$srEnabled = Ask-YesNo "Enable survival_runway filter?" (Coalesce-Bool (Get-Property $survival 'enabled') $true)
$srDays = [double](Ask-WithDefault "  target_survival_days (3=three days, 7=a week)" (Coalesce-Default (Get-Property $survival 'target_survival_days') "5"))
$srTvlMult = [double](Ask-WithDefault "  min_tvl_multiple_of_position (TVL >= this x your max position)" (Coalesce-Default (Get-Property $survival 'min_tvl_multiple_of_position') "200"))
$srVolPct = [double](Ask-WithDefault "  min_daily_volume_pct_of_tvl (% of TVL traded per day)" (Coalesce-Default (Get-Property $survival 'min_daily_volume_pct_of_tvl') "5.0"))
$srActiveWeek = Ask-YesNo "  require_active_week (skip pools with zero weekly volume)" (Coalesce-Bool (Get-Property $survival 'require_active_week') $true)

Write-Host ""
Write-Host "quote_only_entry: 'never buy their stupid token at the start of a position'" -ForegroundColor Cyan
$qoeEnabled = Ask-YesNo "Enable quote_only_entry policy?" (Coalesce-Bool (Get-Property $quoteOnly 'enabled') $true)
$existingQoeQuotes = Get-Property $quoteOnly 'allowed_quote_symbols'
if ($null -ne $existingQoeQuotes) {
    $qoeDefault = ($existingQoeQuotes | ForEach-Object { [string]$_ }) -join ","
} else {
    $qoeDefault = $quotesRaw
}
$qoeQuotesRaw = Ask-WithDefault "  allowed_quote_symbols (deposit-only assets)" $qoeDefault
$qoeRequireClmm = Ask-YesNo "  require_concentrated_pool (only CLMM pools qualify)" (Coalesce-Bool (Get-Property $quoteOnly 'require_concentrated_pool') $false)
$qoeAllowQQ = Ask-YesNo "  allow_quote_quote_pools (allow USDC/USDT etc)" (Coalesce-Bool (Get-Property $quoteOnly 'allow_quote_quote_pools') $true)

Write-Host ""
Write-Host "honeypot_guard: sell-tax cap + freeze/hook/permanent-delegate vetoes" -ForegroundColor Cyan
$hgEnabled = Ask-YesNo "Enable honeypot_guard?" (Coalesce-Bool (Get-Property $honeypot 'enabled') $true)
$hgMaxTax = [double](Ask-WithDefault "  max_sell_tax_percent (refuse pools above this on-chain sell tax)" (Coalesce-Default (Get-Property $honeypot 'max_sell_tax_percent') "30.0"))
$hgFreeze = Ask-YesNo "  reject_if_freeze_authority_set" (Coalesce-Bool (Get-Property $honeypot 'reject_if_freeze_authority_set') $true)
$hgHook = Ask-YesNo "  reject_if_transfer_hook_set" (Coalesce-Bool (Get-Property $honeypot 'reject_if_transfer_hook_set') $true)
$hgPermDel = Ask-YesNo "  reject_if_permanent_delegate_set" (Coalesce-Bool (Get-Property $honeypot 'reject_if_permanent_delegate_set') $true)
$hgFailOpen = Ask-YesNo "  fail_open_when_no_rpc (accept candidates when no RPC is configured)" (Coalesce-Bool (Get-Property $honeypot 'fail_open_when_no_rpc') $false)

Write-Host ""
Write-Host "pool_age_guard: refuse pools that are too young (or too old)" -ForegroundColor Cyan
$pagEnabled = Ask-YesNo "Enable pool_age_guard?" (Coalesce-Bool (Get-Property $poolAge 'enabled') $true)
$pagMinMin = [double](Ask-WithDefault "  min_age_minutes (skip pools younger than this)" (Coalesce-Default (Get-Property $poolAge 'min_age_minutes') "60"))
$pagMaxDays = [double](Ask-WithDefault "  max_age_days (0 = no upper bound)" (Coalesce-Default (Get-Property $poolAge 'max_age_days') "0"))
$pagFailOpen = Ask-YesNo "  fail_open_when_unknown (accept pools with unknown age)" (Coalesce-Bool (Get-Property $poolAge 'fail_open_when_unknown') $false)

Write-Host ""
Write-Host "mint_authority_guard: refuse base tokens that can still mint unlimited supply" -ForegroundColor Cyan
$magEnabled = Ask-YesNo "Enable mint_authority_guard?" (Coalesce-Bool (Get-Property $mintAuth 'enabled') $true)
$magReject = Ask-YesNo "  reject_if_mint_authority_set" (Coalesce-Bool (Get-Property $mintAuth 'reject_if_mint_authority_set') $true)
$magFailOpen = Ask-YesNo "  fail_open_when_no_rpc" (Coalesce-Bool (Get-Property $mintAuth 'fail_open_when_no_rpc') $false)

Write-Host ""
Write-Host "lp_lock_guard: require LP supply burned/locked so liquidity can't be pulled" -ForegroundColor Cyan
$llgEnabled = Ask-YesNo "Enable lp_lock_guard?" (Coalesce-Bool (Get-Property $lpLock 'enabled') $true)
$llgMinPct = [double](Ask-WithDefault "  min_locked_or_burned_pct" (Coalesce-Default (Get-Property $lpLock 'min_locked_or_burned_pct') "90.0"))
$llgClmm = Ask-YesNo "  apply_to_concentrated_pools (CLMM uses NFT positions, off by default)" (Coalesce-Bool (Get-Property $lpLock 'apply_to_concentrated_pools') $false)
$llgFailOpen = Ask-YesNo "  fail_open_when_no_rpc" (Coalesce-Bool (Get-Property $lpLock 'fail_open_when_no_rpc') $false)

Write-Host ""
Write-Host "price_impact_guard: refuse pools too small to absorb a max_position_usd entry" -ForegroundColor Cyan
$pigEnabled = Ask-YesNo "Enable price_impact_guard?" (Coalesce-Bool (Get-Property $priceImpact 'enabled') $true)
$pigMax = [double](Ask-WithDefault "  max_impact_percent" (Coalesce-Default (Get-Property $priceImpact 'max_impact_percent') "1.0"))
$pigQuoteFrac = [double](Ask-WithDefault "  quote_side_fraction (0.5 = standard AMM)" (Coalesce-Default (Get-Property $priceImpact 'quote_side_fraction') "0.5"))

Write-Host ""
Write-Host "fee_apr_floor: require minimum fee-only APR so we don't chase farm-reward APR" -ForegroundColor Cyan
$fafEnabled = Ask-YesNo "Enable fee_apr_floor?" (Coalesce-Bool (Get-Property $feeFloor 'enabled') $true)
$fafMin = [double](Ask-WithDefault "  min_fee_apr_percent" (Coalesce-Default (Get-Property $feeFloor 'min_fee_apr_percent') "30.0"))

Write-Host ""
Write-Host "rpc_health_gate: refuse to scan if no Solana RPC is actually answering" -ForegroundColor Cyan
$rhgEnabled = Ask-YesNo "Enable rpc_health_gate?" (Coalesce-Bool (Get-Property $rpcGate 'enabled') $true)
$rhgMin = [int](Ask-WithDefault "  min_healthy_rpcs" (Coalesce-Default (Get-Property $rpcGate 'min_healthy_rpcs') "1"))
$rhgRequire = Ask-YesNo "  require_when_no_rpc_configured (fail even with 0 RPCs configured)" (Coalesce-Bool (Get-Property $rpcGate 'require_when_no_rpc_configured') $false)

$existingFreezeWhitelist = Get-Property $honeypot 'allowed_freeze_authority_mints'
if ($null -ne $existingFreezeWhitelist) {
    $freezeWhitelist = @($existingFreezeWhitelist | ForEach-Object { [string]$_ })
} else {
    $freezeWhitelist = @(
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    )
}

$existingMintAuthWhitelist = Get-Property $mintAuth 'allowed_mint_authority_mints'
if ($null -ne $existingMintAuthWhitelist) {
    $mintAuthWhitelist = @($existingMintAuthWhitelist | ForEach-Object { [string]$_ })
} else {
    $mintAuthWhitelist = @(
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    )
}

$fallbacks = New-Object System.Collections.Generic.List[string]
$existingFallbacks = @()
if ($existingEnv.ContainsKey('SOLANA_RPC_URLS') -and $existingEnv['SOLANA_RPC_URLS']) {
    $existingFallbacks = $existingEnv['SOLANA_RPC_URLS'].Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}
if ($existingFallbacks.Count -eq 0) {
    $existingFallbacks = @("https://solana-rpc.publicnode.com", "https://solana.drpc.org")
}
foreach ($url in $existingFallbacks) { [void]$fallbacks.Add($url) }

Write-Host ""
Write-Host "Backup RPC URLs (currently $($fallbacks.Count) configured). Paste one URL per line. Blank line to finish." -ForegroundColor Cyan
while ($true) {
    $rpc = Read-Host "Backup RPC URL (blank to keep existing)"
    if ([string]::IsNullOrWhiteSpace($rpc)) { break }
    [void]$fallbacks.Add($rpc.Trim())
}

$allowedQuotes = $quotesRaw.Split(",") | ForEach-Object { $_.Trim().ToUpperInvariant() } | Where-Object { $_ }
$qoeQuotes = $qoeQuotesRaw.Split(",") | ForEach-Object { $_.Trim().ToUpperInvariant() } | Where-Object { $_ }

$config = [ordered]@{
    dry_run = $true
    min_apr = $minApr
    apr_field = (Coalesce-Default (Get-Property $existing 'apr_field') "apr24h")
    raydium_api_base = $raydiumApiBase
    pool_type = (Coalesce-Default (Get-Property $existing 'pool_type') "all")
    sort_type = (Coalesce-Default (Get-Property $existing 'sort_type') "desc")
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
    survival_runway = [ordered]@{
        enabled = [bool]$srEnabled
        target_survival_days = $srDays
        min_tvl_multiple_of_position = $srTvlMult
        min_daily_volume_pct_of_tvl = $srVolPct
        require_active_week = [bool]$srActiveWeek
    }
    quote_only_entry = [ordered]@{
        enabled = [bool]$qoeEnabled
        allowed_quote_symbols = @($qoeQuotes)
        require_concentrated_pool = [bool]$qoeRequireClmm
        allow_quote_quote_pools = [bool]$qoeAllowQQ
    }
    honeypot_guard = [ordered]@{
        enabled = [bool]$hgEnabled
        max_sell_tax_percent = $hgMaxTax
        reject_if_freeze_authority_set = [bool]$hgFreeze
        reject_if_transfer_hook_set = [bool]$hgHook
        reject_if_permanent_delegate_set = [bool]$hgPermDel
        allowed_freeze_authority_mints = @($freezeWhitelist)
        fail_open_when_no_rpc = [bool]$hgFailOpen
        rpc_timeout_seconds = [double](Coalesce-Default (Get-Property $honeypot 'rpc_timeout_seconds') "8.0")
    }
    pool_age_guard = [ordered]@{
        enabled = [bool]$pagEnabled
        min_age_minutes = $pagMinMin
        max_age_days = $pagMaxDays
        fail_open_when_unknown = [bool]$pagFailOpen
    }
    mint_authority_guard = [ordered]@{
        enabled = [bool]$magEnabled
        reject_if_mint_authority_set = [bool]$magReject
        allowed_mint_authority_mints = @($mintAuthWhitelist)
        fail_open_when_no_rpc = [bool]$magFailOpen
    }
    lp_lock_guard = [ordered]@{
        enabled = [bool]$llgEnabled
        min_locked_or_burned_pct = $llgMinPct
        apply_to_concentrated_pools = [bool]$llgClmm
        fail_open_when_no_rpc = [bool]$llgFailOpen
        rpc_timeout_seconds = [double](Coalesce-Default (Get-Property $lpLock 'rpc_timeout_seconds') "8.0")
    }
    price_impact_guard = [ordered]@{
        enabled = [bool]$pigEnabled
        max_impact_percent = $pigMax
        quote_side_fraction = $pigQuoteFrac
    }
    fee_apr_floor = [ordered]@{
        enabled = [bool]$fafEnabled
        min_fee_apr_percent = $fafMin
    }
    rpc_health_gate = [ordered]@{
        enabled = [bool]$rhgEnabled
        min_healthy_rpcs = $rhgMin
        require_when_no_rpc_configured = [bool]$rhgRequire
    }
}

$configDir = Split-Path -Parent $ConfigPath
if ($configDir -and -not (Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir | Out-Null }
$config | ConvertTo-Json -Depth 6 | Set-Content -Path $ConfigPath -Encoding UTF8

$allFallbacks = ($fallbacks | Where-Object { $_ -and $_ -ne $primaryRpc } | Select-Object -Unique) -join ","
@(
    "# Raydium-LP1 local live data sources. This file is ignored by Git.",
    "RAYDIUM_API_BASE=$raydiumApiBase",
    "SOLANA_RPC_URL=$primaryRpc",
    "SOLANA_RPC_URLS=$allFallbacks"
) | Set-Content -Path $EnvPath -Encoding UTF8

Write-Host ""
Write-Host "Wrote $ConfigPath (min_apr=$minApr, all 9 named filters configured)" -ForegroundColor Green
Write-Host "Wrote $EnvPath with your live RPC/API URLs" -ForegroundColor Green
Write-Host "All values you entered are now the defaults next time you run the wizard." -ForegroundColor Green
Write-Host ""
Write-Host "Next paste/run:" -ForegroundColor Cyan
Write-Host ".\scripts\doctor.ps1"
Write-Host ".\scripts\run_scan.ps1 -CheckRpc -WriteReports"

if (Ask-YesNo "Run doctor check now?" $true) {
    & "$ScriptDir\doctor.ps1"
}
