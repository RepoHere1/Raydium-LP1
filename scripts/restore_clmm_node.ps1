# restore_clmm_node.ps1 — put back deleted raydium_clmm_node files (required for LIVE opens)
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore_clmm_node.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[!!] git not found on PATH. Install Git for Windows first." -ForegroundColor Yellow
    exit 1
}

Write-Host "Restoring src/raydium_lp1/raydium_clmm_node from current branch..." -ForegroundColor Cyan
git restore --source=HEAD --staged --worktree src/raydium_lp1/raydium_clmm_node/

if ($LASTEXITCODE -ne 0) {
    git checkout HEAD -- src/raydium_lp1/raydium_clmm_node/
}

Write-Host "[OK] Restored. Checking open_position.mjs..." -ForegroundColor Green
$open = Join-Path $repo "src\raydium_lp1\raydium_clmm_node\open_position.mjs"
if (Test-Path -LiteralPath $open) {
    Write-Host "[OK] $open exists" -ForegroundColor Green
} else {
    Write-Host "[!!] Still missing: $open — run: git fetch origin && git reset --hard origin/cursor/no-escrow-policy-3b04" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Next (Node deps for CLMM scripts):" -ForegroundColor Cyan
Write-Host "  cd src\raydium_lp1\raydium_clmm_node" -ForegroundColor White
Write-Host "  npm install" -ForegroundColor White
