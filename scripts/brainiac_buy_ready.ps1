# brainiac_buy_ready.ps1 - one-time setup so Brainiac LIVE buy orders work
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\brainiac_buy_ready.ps1

param(
    [switch]$SkipNpm
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Write-Step([string]$Msg) {
    Write-Host $Msg -ForegroundColor Cyan
}

function Write-Ok([string]$Msg) {
    Write-Host "[OK] $Msg" -ForegroundColor Green
}

function Write-Warn([string]$Msg) {
    Write-Host "[!!] $Msg" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Brainiac BUY setup - Raydium-LP1" -ForegroundColor White
Write-Host "Repo: $RepoRoot" -ForegroundColor DarkGray
Write-Host ""

# 1) Restore CLMM Node scripts if deleted
$clmmDir = Join-Path $RepoRoot "src\raydium_lp1\raydium_clmm_node"
$mustHave = @("open_position.mjs", "close_position.mjs", "list_owner_positions.mjs", "package.json")
$missing = New-Object System.Collections.Generic.List[string]
foreach ($name in $mustHave) {
    $p = Join-Path $clmmDir $name
    if (-not (Test-Path -LiteralPath $p)) {
        [void]$missing.Add($name)
    }
}

if ($missing.Count -gt 0) {
    Write-Warn ("Missing CLMM Node files: " + ($missing -join ", "))
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCmd) {
        Write-Step "Restoring raydium_clmm_node from git..."
        & git restore --source=HEAD --staged --worktree src/raydium_lp1/raydium_clmm_node/
        if ($LASTEXITCODE -ne 0) {
            & git checkout HEAD -- src/raydium_lp1/raydium_clmm_node/
        }
        Write-Ok "Restored raydium_clmm_node"
    }
    else {
        Write-Warn "git not on PATH - run: git restore src/raydium_lp1/raydium_clmm_node/"
    }
}
else {
    Write-Ok "raydium_clmm_node files present"
}

# 2) npm install
if (-not $SkipNpm) {
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($node -and $npm) {
        $nm = Join-Path $clmmDir "node_modules"
        if (-not (Test-Path -LiteralPath $nm)) {
            Write-Step "Running npm install in raydium_clmm_node..."
            Push-Location $clmmDir
            & npm install --no-fund --no-audit
            Pop-Location
            Write-Ok "npm install done"
        }
        else {
            Write-Ok "node_modules already present"
        }
    }
    else {
        Write-Warn "Node.js not found - install from https://nodejs.org then re-run"
    }
}

# 3) Python
. (Join-Path $PSScriptRoot "_resolve_python.ps1")
if (-not $ResolvedPythonExe) {
    Write-Warn "Python not found. Run: powershell -File .\scripts\fix_python_once.ps1"
    exit 1
}
Write-Ok ("Python: " + $ResolvedPythonExe)

# 4) settings.json
$settingsPath = Join-Path $RepoRoot "config\settings.json"
if (-not (Test-Path -LiteralPath $settingsPath)) {
    $safe = Join-Path $RepoRoot "config\settings.safe.json"
    $example = Join-Path $RepoRoot "config\settings.example.json"
    if (Test-Path -LiteralPath $safe) {
        Copy-Item -LiteralPath $safe -Destination $settingsPath -Force
        Write-Ok "Created config\settings.json from settings.safe.json"
    }
    elseif (Test-Path -LiteralPath $example) {
        Copy-Item -LiteralPath $example -Destination $settingsPath -Force
        Write-Ok "Created config\settings.json from settings.example.json"
    }
    else {
        Write-Warn "No settings template - create config\settings.json manually"
    }
}

# 5) Brainiac strategy
$env:PYTHONPATH = Join-Path $RepoRoot "src"
$pyApply = 'import json; from raydium_lp1.brainiac_open_runner import apply_brainiac_strategy_settings; print(json.dumps(apply_brainiac_strategy_settings()))'
$applyOut = & $ResolvedPythonExe @ResolvedPythonArgs -c $pyApply 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Brainiac strategy applied (live mode, no escrow policy)"
}
else {
    Write-Warn ("Could not patch settings: " + $applyOut)
}

# 6) Live readiness
$pyReady = 'import json; from raydium_lp1.live_executor import live_readiness_check; print(json.dumps(live_readiness_check()))'
$readyRaw = & $ResolvedPythonExe @ResolvedPythonArgs -c $pyReady 2>&1 | Out-String
try {
    $ready = $readyRaw | ConvertFrom-Json
    if ($ready.ready_to_sign) {
        Write-Ok "LIVE readiness: ready_to_sign"
    }
    else {
        Write-Warn "LIVE readiness blockers:"
        foreach ($b in $ready.blockers) {
            Write-Host ("  - " + $b) -ForegroundColor Yellow
        }
    }
}
catch {
    Write-Warn ("Readiness check output: " + $readyRaw)
}

# 7) Wizard state template
$wizPath = Join-Path $RepoRoot "config\brainiac_wizard_last.json"
$wizEx = Join-Path $RepoRoot "config\brainiac_wizard_last.example.json"
if (-not (Test-Path -LiteralPath $wizPath)) {
    if (Test-Path -LiteralPath $wizEx) {
        Copy-Item -LiteralPath $wizEx -Destination $wizPath -Force
        Write-Ok "Created config\brainiac_wizard_last.json"
    }
}

# 8) Fix common LIVE blockers (Node + RPC)
$fixBlockers = Join-Path $PSScriptRoot "fix_live_blockers.ps1"
if (Test-Path -LiteralPath $fixBlockers) {
    Write-Step "Checking Node + RPC blockers..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $fixBlockers -SkipNpm:$(-not (Get-Command npm -ErrorAction SilentlyContinue))
}

Write-Host ""
Write-Host "=== BRAINIAC BUY (from this folder) ===" -ForegroundColor Green
Write-Host "  .\brainiac_buy.cmd YOUR_POOL_ID 1" -ForegroundColor Cyan
Write-Host "  .\brainiac_wizard.cmd -Live" -ForegroundColor Cyan
Write-Host ""
Write-Host "If in_range_factor blocks, edit config\brainiac_wizard_last.json:" -ForegroundColor DarkGray
Write-Host '  "min_in_range_factor": 0.50' -ForegroundColor DarkGray
Write-Host ""
