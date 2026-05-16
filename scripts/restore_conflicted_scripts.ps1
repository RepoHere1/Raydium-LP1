# Restore known script paths from origin/main when merge conflict markers broke them.
# Safe for local config: only replaces tracked repo files, not config\settings.json or .env.
param([switch]$WhatIf)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$paths = @(
    "scripts\run_scan.ps1",
    "scripts\watch_verdict.ps1",
    "src\raydium_lp1\verdicts.py"
)

Write-Host "Fetching origin/main..." -ForegroundColor Cyan
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw "git fetch failed." }

foreach ($rel in $paths) {
    if ($WhatIf) {
        Write-Host "Would restore: $rel" -ForegroundColor Yellow
        continue
    }
    Write-Host "Restoring $rel from origin/main..." -ForegroundColor Green
    git checkout origin/main -- $rel
    if ($LASTEXITCODE -ne 0) { throw "git checkout failed for $rel" }
}

Write-Host ""
Write-Host "Done. Run scanner (two lines):" -ForegroundColor Cyan
Write-Host '  cd C:\Users\Taylor\Raydium-LP1'
Write-Host '  .\scripts\run_scan.ps1 -Loop -SpawnWatcher -WriteRejections'
