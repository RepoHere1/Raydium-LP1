param(
    [string]$EnvPath = ".env",
    [string]$ConfigPath = "config\settings.json",
    [switch]$SkipSettingsJson
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

function Test-HttpRpcUrl {
    param([string]$Candidate)
    $u = $Candidate.Trim()
    if ($u.Length -lt 12) { return $false }
    if ($u -notmatch '^(https?)://') { return $false }
    try {
        $uri = [System.Uri]$u
        return [bool]$uri.Host
    } catch {
        return $false
    }
}

Write-Host ""
Write-Host "Raydium-LP1 RPC wizard (writes $EnvPath ; optional sync to $ConfigPath)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Rules:" -ForegroundColor DarkGray
Write-Host "  - SOLANA_RPC_URL = one primary HTTPS RPC (Helius, etc.)." -ForegroundColor DarkGray
Write-Host "  - SOLANA_RPC_URLS = extra fallbacks only, comma-separated, each must be a full URL." -ForegroundColor DarkGray
Write-Host "  - Never put a lone letter after a comma (that caused the 'y' crash)." -ForegroundColor DarkGray
Write-Host ""

$envDefaults = Read-EnvDefaults -Path $EnvPath

$apiDefault = if ($envDefaults["RAYDIUM_API_BASE"]) { $envDefaults["RAYDIUM_API_BASE"] } else { "https://api-v3.raydium.io" }
$api = Ask-WithDefault "Raydium API base" $apiDefault

$primaryDefault = if ($envDefaults["SOLANA_RPC_URL"]) { $envDefaults["SOLANA_RPC_URL"] } else { "https://api.mainnet-beta.solana.com" }
while ($true) {
    $primary = Ask-WithDefault "Primary Solana RPC (SOLANA_RPC_URL)" $primaryDefault
    if (Test-HttpRpcUrl $primary) { break }
    Write-Host "  That does not look like https://... with a host. Try again." -ForegroundColor Yellow
}

$fallbacks = New-Object System.Collections.Generic.List[string]
if ($envDefaults["SOLANA_RPC_URLS"]) {
    foreach ($entry in $envDefaults["SOLANA_RPC_URLS"].Split(",")) {
        $entry = $entry.Trim()
        if ($entry -and $entry -ne $primary) { [void]$fallbacks.Add($entry) }
    }
}
if ($fallbacks.Count -eq 0) {
    $fallbacks.Add("https://solana-rpc.publicnode.com")
    $fallbacks.Add("https://solana.drpc.org")
}

Write-Host ""
Write-Host "Backup RPCs (SOLANA_RPC_URLS). Each must be a full URL. Press Enter when done adding." -ForegroundColor DarkGray
Write-Host "Current list:" -ForegroundColor DarkGray
foreach ($e in $fallbacks) { Write-Host "  - $e" -ForegroundColor DarkGray }
Write-Host "Type 'clear' on a line to reset list, or paste one URL per line; empty line = finish."
while ($true) {
    $line = Read-Host "Add backup RPC URL"
    if ([string]::IsNullOrWhiteSpace($line)) { break }
    $t = $line.Trim()
    if ($t.ToLowerInvariant() -eq "clear") {
        $fallbacks.Clear()
        Write-Host "  (cleared)" -ForegroundColor Yellow
        continue
    }
    if (-not (Test-HttpRpcUrl $t)) {
        Write-Host "  Skipped (not a valid http/https URL): $t" -ForegroundColor Yellow
        continue
    }
    if ($t -eq $primary) {
        Write-Host "  Skipped (same as primary)." -ForegroundColor DarkGray
        continue
    }
    if (-not $fallbacks.Contains($t)) { [void]$fallbacks.Add($t) }
}

$allForJson = New-Object System.Collections.Generic.List[string]
[void]$allForJson.Add($primary)
foreach ($f in $fallbacks) {
    if ($f -and $f -ne $primary -and -not $allForJson.Contains($f)) { [void]$allForJson.Add($f) }
}

$allFallbacks = ($fallbacks | Where-Object { $_ -and $_ -ne $primary }) -join ","

@(
    "# Raydium-LP1 local live data sources. This file is ignored by Git.",
    "# SOLANA_RPC_URL = primary endpoint (one URL).",
    "# SOLANA_RPC_URLS = optional fallbacks only: comma-separated FULL https URLs (no trailing junk).",
    "RAYDIUM_API_BASE=$api",
    "SOLANA_RPC_URL=$primary",
    "SOLANA_RPC_URLS=$allFallbacks"
) | Set-Content -Path $EnvPath -Encoding UTF8

Write-Host ""
Write-Host "Wrote $EnvPath" -ForegroundColor Green

if (-not $SkipSettingsJson -and (Test-Path $ConfigPath)) {
    $tmpJson = [System.IO.Path]::GetTempFileName() + ".urls.json"
    try {
        ($allForJson | ConvertTo-Json -Compress) | Set-Content -Path $tmpJson -Encoding UTF8
        $pythonExe = "python"
        $pythonPrefix = @()
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $pythonExe = "py"
            $pythonPrefix = @("-3")
        }
        $env:PYTHONPATH = "src"
        & $pythonExe @pythonPrefix "scripts\apply_rpc_urls_to_settings.py" --settings $ConfigPath --urls-json $tmpJson --raydium-api-base $api
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Could not merge RPC list into $ConfigPath (scanner still reads .env)." -ForegroundColor Yellow
        }
    } finally {
        Remove-Item -LiteralPath $tmpJson -ErrorAction SilentlyContinue
    }
} elseif (-not (Test-Path $ConfigPath)) {
    Write-Host "No $ConfigPath yet — run .\scripts\setup_wizard.ps1 later; .env alone is enough for RPC." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Example .env (what you should have):" -ForegroundColor Cyan
Write-Host '  RAYDIUM_API_BASE=https://api-v3.raydium.io'
Write-Host '  SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY'
Write-Host '  SOLANA_RPC_URLS=https://solana-rpc.publicnode.com,https://solana.drpc.org'
Write-Host ""
Write-Host "Next: .\scripts\doctor.ps1   or   .\scripts\run_scan.ps1 -CheckRpc" -ForegroundColor Cyan
