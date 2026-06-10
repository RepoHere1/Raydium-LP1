# install_here.ps1 — one-shot: git sync + LIVE stack on this PC
# Usage (from repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_here.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_here.ps1 -StashLocal

param(
    [switch]$StashLocal,
    [switch]$SkipHelius,
    [string]$Branch = "cursor/no-escrow-policy-3b04"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Write-Step([string]$Msg) { Write-Host $Msg -ForegroundColor Cyan }
function Write-Ok([string]$Msg) { Write-Host "[OK] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "[!!] $Msg" -ForegroundColor Yellow }

$TargetHead = "e91c8ce"

Write-Host ""
Write-Host "Raydium-LP1 install_here" -ForegroundColor White
Write-Host "Repo: $RepoRoot" -ForegroundColor DarkGray
Write-Host "Branch: $Branch" -ForegroundColor DarkGray
Write-Host ""

# --- Git ---
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Warn "git not on PATH — install Git for Windows, then re-run."
    exit 1
}

$remoteUrl = (& git remote get-url origin 2>$null)
if ($remoteUrl -and $remoteUrl -notmatch "RepoHere1/Raydium-LP1") {
    Write-Warn "origin is not RepoHere1/Raydium-LP1: $remoteUrl"
    Write-Step "Fix with: git remote set-url origin https://github.com/RepoHere1/Raydium-LP1.git"
}

if ($StashLocal) {
    $dirty = (& git status --porcelain 2>$null)
    if ($dirty) {
        Write-Step "Stashing local changes..."
        & git stash push -m "install_here $(Get-Date -Format o)"
        Write-Ok "Stashed (git stash pop to restore)"
    }
}

Write-Step "Fetching origin..."
& git fetch origin
if ($LASTEXITCODE -ne 0) {
    Write-Warn "git fetch failed — check network / GitHub access"
    exit 1
}

$localBranch = (& git branch --show-current 2>$null)
if ($localBranch -ne $Branch) {
    Write-Step "Checking out $Branch..."
    & git checkout $Branch 2>$null
    if ($LASTEXITCODE -ne 0) {
        & git checkout -b $Branch "origin/$Branch"
    }
}

Write-Step "Pulling latest..."
& git pull origin $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Warn "git pull failed — resolve conflicts or run: git reset --hard origin/$Branch"
    exit 1
}

$head = (& git rev-parse --short HEAD 2>$null)
Write-Ok "HEAD $head on $Branch"
if ($head -ne $TargetHead) {
    Write-Warn "Expected tip $TargetHead — you may be 1+ commits behind or ahead. Run: git fetch origin; git log --oneline -3"
}

# --- Python PATH ---
$fixPy = Join-Path $RepoRoot "scripts\fix_python_once.ps1"
if (Test-Path -LiteralPath $fixPy) {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        Write-Step "Fixing Python PATH..."
        & powershell -NoProfile -ExecutionPolicy Bypass -File $fixPy
    }
}

# --- Full LIVE bootstrap ---
$ready = Join-Path $RepoRoot "scripts\brainiac_buy_ready.ps1"
if (Test-Path -LiteralPath $ready) {
    Write-Step "Running brainiac_buy_ready..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ready
}

# --- Helius RPC (optional) ---
if (-not $SkipHelius) {
    $envPath = Join-Path $RepoRoot ".env"
    $needsRpc = $true
    if (Test-Path -LiteralPath $envPath) {
        $envText = Get-Content -LiteralPath $envPath -Raw -Encoding UTF8
        if ($envText -match "helius-rpc\.com" -or $envText -match "SOLANA_RPC_URL\s*=\s*https?://") {
            $needsRpc = $false
        }
    }
    if ($needsRpc) {
        Write-Warn "No Helius/mainnet RPC in .env — run .\save_helius.cmd when ready"
    }
    else {
        Write-Ok "RPC present in .env"
    }
}

Write-Host ""
Write-Host "=== INSTALLED — next steps ===" -ForegroundColor Green
Write-Host "  .\brainiac_wizard.cmd" -ForegroundColor Cyan
Write-Host "  .\brainiac_buy.cmd POOL_ID 0.25" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verify: git log --oneline -1  (want $TargetHead)" -ForegroundColor DarkGray
Write-Host ""
