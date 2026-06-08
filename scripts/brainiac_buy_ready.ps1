<#
.SYNOPSIS
  One-time setup so Brainiac LIVE buy orders work again on this PC.

.EXAMPLE
  cd C:\Users\Taylor\Raydium-LP1
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\brainiac_buy_ready.ps1
#>
param(
    [switch]$SkipNpm
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Write-Step([string]$Msg) { Write-Host $Msg -ForegroundColor Cyan }
function Write-Ok([string]$Msg) { Write-Host "[OK] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "[!!] $Msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "Brainiac BUY setup — Raydium-LP1" -ForegroundColor White
Write-Host "Repo: $RepoRoot" -ForegroundColor DarkGray
Write-Host ""

# --- 1) Restore CLMM Node scripts if deleted ---
$clmmDir = Join-Path $RepoRoot "src\raydium_lp1\raydium_clmm_node"
$mustHave = @(
    "open_position.mjs",
    "close_position.mjs",
    "list_owner_positions.mjs",
    "package.json"
)
$missing = @($mustHave | Where-Object { -not (Test-Path (Join-Path $clmmDir $_)) })
if ($missing.Count -gt 0) {
    Write-Warn "Missing CLMM Node files: $($missing -join ', ')"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Step "Restoring raydium_clmm_node from git..."
        git restore --source=HEAD --staged --worktree src/raydium_lp1/raydium_clmm_node/ 2>$null
        if ($LASTEXITCODE -ne 0) {
            git checkout HEAD -- src/raydium_lp1/raydium_clmm_node/
        }
        Write-Ok "Restored raydium_clmm_node"
    } else {
        Write-Warn "git not on PATH — run: git restore src/raydium_lp1/raydium_clmm_node/"
    }
} else {
    Write-Ok "raydium_clmm_node files present"
}

# --- 2) npm install ---
if (-not $SkipNpm) {
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($node -and $npm) {
        $nm = Join-Path $clmmDir "node_modules"
        if (-not (Test-Path -LiteralPath $nm)) {
            Write-Step "Running npm install in raydium_clmm_node..."
            Push-Location $clmmDir
            npm install --no-fund --no-audit 2>&1 | Out-Host
            Pop-Location
            Write-Ok "npm install done"
        } else {
            Write-Ok "node_modules already present"
        }
    } else {
        Write-Warn "Node.js not found — install from https://nodejs.org then re-run this script"
    }
}

# --- 3) Python ---
. (Join-Path $PSScriptRoot "_resolve_python.ps1")
if (-not $ResolvedPythonExe) {
    Write-Warn "Python not found. Run: powershell -File .\scripts\fix_python_once.ps1"
    Write-Host "  Or install: winget install Python.Python.3.12" -ForegroundColor Yellow
    exit 1
}
Write-Ok "Python: $ResolvedPythonExe"

# --- 4) settings.json ---
$settingsPath = Join-Path $RepoRoot "config\settings.json"
if (-not (Test-Path -LiteralPath $settingsPath)) {
    $templates = @(
        (Join-Path $RepoRoot "config\settings.safe.json"),
        (Join-Path $RepoRoot "config\settings.example.json")
    )
    $src = $templates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($src) {
        Copy-Item -LiteralPath $src -Destination $settingsPath -Force
        Write-Ok "Created config\settings.json from $(Split-Path $src -Leaf)"
    } else {
        Write-Warn "No settings template — create config\settings.json manually"
    }
}

# --- 5) Brainiac strategy + LIVE mode ---
$env:PYTHONPATH = Join-Path $RepoRoot "src"
$pyCodeApply = "import json; from raydium_lp1.brainiac_open_runner import apply_brainiac_strategy_settings; print(json.dumps(apply_brainiac_strategy_settings(), indent=2))"
$applyOut = & $ResolvedPythonExe @ResolvedPythonArgs -c $pyCodeApply 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Brainiac strategy applied (lp_active_strategy, mode=live, dry_run=false)"
} else {
    Write-Warn "Could not patch settings: $applyOut"
}

# --- 6) Live readiness ---
$pyCodeReady = "import json; from raydium_lp1.live_executor import live_readiness_check; print(json.dumps(live_readiness_check(), indent=2))"
$readyJson = & $ResolvedPythonExe @ResolvedPythonArgs -c $pyCodeReady 2>&1 | Out-String
try {
    $ready = $readyJson | ConvertFrom-Json
    if ($ready.ready_to_sign) {
        Write-Ok "LIVE readiness: ready_to_sign"
    } else {
        Write-Warn "LIVE readiness blockers:"
        foreach ($b in $ready.blockers) { Write-Host "  - $b" -ForegroundColor Yellow }
    }
} catch {
    Write-Warn "Readiness check output: $readyJson"
}

# --- 7) Wizard state template ---
$wizPath = Join-Path $RepoRoot "config\brainiac_wizard_last.json"
$wizEx = Join-Path $RepoRoot "config\brainiac_wizard_last.example.json"
if (-not (Test-Path -LiteralPath $wizPath) -and (Test-Path -LiteralPath $wizEx)) {
    Copy-Item -LiteralPath $wizEx -Destination $wizPath -Force
    Write-Ok "Created config\brainiac_wizard_last.json from example"
}

Write-Host ""
Write-Host "=== BRAINIAC BUY COMMANDS (from this folder) ===" -ForegroundColor Green
Write-Host ""
Write-Host "Interactive LIVE (asks pool + settings):" -ForegroundColor White
Write-Host "  .\brainiac_wizard.cmd -Live" -ForegroundColor Cyan
Write-Host ""
Write-Host "One-line LIVE buy (pool + USD):" -ForegroundColor White
Write-Host '  .\brainiac_buy.cmd YOUR_POOL_ID 1' -ForegroundColor Cyan
Write-Host '  .\brainiac_wizard.cmd -Live -PoolId "YOUR_POOL_ID" -DepositUsd 1' -ForegroundColor Cyan
Write-Host ""
Write-Host "Preview only (no on-chain tx):" -ForegroundColor White
Write-Host '  .\brainiac_wizard.cmd -PoolId "YOUR_POOL_ID" -DepositUsd 1 -PreviewOnly' -ForegroundColor Cyan
Write-Host ""
Write-Host "Order type: brainiac_cursor_success_80_skewed_no_escrow (NO ESCROW PAID)" -ForegroundColor DarkGray
Write-Host ""
