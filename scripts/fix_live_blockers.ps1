# fix_live_blockers.ps1 - fix Node.js + Solana RPC blockers for Brainiac LIVE
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fix_live_blockers.ps1
#   powershell -File .\scripts\fix_live_blockers.ps1 -InstallNode

param(
    [switch]$InstallNode,
    [switch]$SkipNpm
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Write-Ok([string]$Msg) { Write-Host "[OK] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "[!!] $Msg" -ForegroundColor Yellow }
function Write-Step([string]$Msg) { Write-Host $Msg -ForegroundColor Cyan }

$DefaultRpcs = @(
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com",
    "https://solana.drpc.org"
)

Write-Host ""
Write-Host "Fix LIVE blockers (Node + RPC)" -ForegroundColor White
Write-Host ""

# --- Node.js ---
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Warn "Node.js not found - required for CLMM opens (open_position.mjs)"
    if ($InstallNode) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            Write-Step "Installing Node.js LTS via winget..."
            & winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
            Write-Warn "Close PowerShell, open NEW window, re-run this script, then npm install runs."
        }
        else {
            Write-Host "  Install manually: https://nodejs.org/en/download (LTS)" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "  Auto-install: powershell -File .\scripts\fix_live_blockers.ps1 -InstallNode" -ForegroundColor Yellow
        Write-Host "  Or download:    https://nodejs.org/en/download" -ForegroundColor Yellow
    }
}
else {
    Write-Ok ("Node: " + $node.Source)
}

# --- npm install in raydium_clmm_node ---
$clmmDir = Join-Path $RepoRoot "src\raydium_lp1\raydium_clmm_node"
$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($node -and $npm -and -not $SkipNpm) {
    if (-not (Test-Path (Join-Path $clmmDir "node_modules"))) {
        Write-Step "npm install in raydium_clmm_node..."
        Push-Location $clmmDir
        & npm install --no-fund --no-audit
        Pop-Location
        Write-Ok "npm install complete"
    }
    else {
        Write-Ok "raydium_clmm_node node_modules present"
    }
}

# --- .env RPC ---
$envPath = Join-Path $RepoRoot ".env"
$primary = "https://api.mainnet-beta.solana.com"
$fallbacks = "https://solana-rpc.publicnode.com,https://solana.drpc.org"

if (-not (Test-Path -LiteralPath $envPath)) {
    Write-Step "Creating .env with public RPC defaults..."
    @(
        "# Raydium-LP1 local config (gitignored)",
        "RAYDIUM_API_BASE=https://api-v3.raydium.io",
        "SOLANA_RPC_URL=$primary",
        "SOLANA_RPC_URLS=$fallbacks"
    ) | Set-Content -Path $envPath -Encoding UTF8
    Write-Ok "Created .env"
}
else {
    $envText = Get-Content -LiteralPath $envPath -Raw -Encoding UTF8
    if ($envText -notmatch "SOLANA_RPC_URL\s*=") {
        Add-Content -Path $envPath -Value "SOLANA_RPC_URL=$primary" -Encoding UTF8
        Write-Ok "Added SOLANA_RPC_URL to .env"
    }
    else {
        Write-Ok ".env has SOLANA_RPC_URL"
    }
}

# --- settings.json solana_rpc_urls ---
. (Join-Path $PSScriptRoot "_resolve_python.ps1")
$settingsPath = Join-Path $RepoRoot "config\settings.json"
if (-not (Test-Path -LiteralPath $settingsPath)) {
    $safe = Join-Path $RepoRoot "config\settings.safe.json"
    if (Test-Path -LiteralPath $safe) {
        Copy-Item -LiteralPath $safe -Destination $settingsPath -Force
        Write-Ok "Created settings.json from settings.safe.json"
    }
}

if ($ResolvedPythonExe -and (Test-Path -LiteralPath $settingsPath)) {
    $env:PYTHONPATH = Join-Path $RepoRoot "src"
    $tmpJson = [System.IO.Path]::GetTempFileName() + ".urls.json"
    try {
        ($DefaultRpcs | ConvertTo-Json -Compress) | Set-Content -Path $tmpJson -Encoding UTF8
        & $ResolvedPythonExe @ResolvedPythonArgs scripts\apply_rpc_urls_to_settings.py --settings $settingsPath --urls-json $tmpJson
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "settings.json solana_rpc_urls updated (3 public endpoints)"
        }
    }
    finally {
        Remove-Item -LiteralPath $tmpJson -ErrorAction SilentlyContinue
    }
}
elseif (-not $ResolvedPythonExe) {
    Write-Warn "Python not found - cannot patch settings.json RPC list"
    Write-Host '  Manually add to config\settings.json:' -ForegroundColor Yellow
    Write-Host '  "solana_rpc_urls": ["https://api.mainnet-beta.solana.com"]' -ForegroundColor White
}

# --- Re-check readiness ---
if ($ResolvedPythonExe) {
    $env:PYTHONPATH = Join-Path $RepoRoot "src"
    $pyReady = 'import json; from raydium_lp1.live_executor import live_readiness_check; print(json.dumps(live_readiness_check()))'
    $readyRaw = & $ResolvedPythonExe @ResolvedPythonArgs -c $pyReady 2>&1 | Out-String
    try {
        $ready = $readyRaw | ConvertFrom-Json
        Write-Host ""
        if ($ready.ready_to_sign) {
            Write-Ok "LIVE readiness: ready_to_sign - you can run brainiac_buy.cmd"
        }
        else {
            Write-Warn "Remaining blockers:"
            foreach ($b in $ready.blockers) {
                Write-Host ("  - " + $b) -ForegroundColor Yellow
            }
        }
    }
    catch {
        Write-Warn $readyRaw
    }
}

Write-Host ""
Write-Host "Helius (faster, optional): get free key at helius.dev, then run:" -ForegroundColor DarkGray
Write-Host "  .\scripts\rpc_wizard.ps1" -ForegroundColor DarkGray
Write-Host ""
