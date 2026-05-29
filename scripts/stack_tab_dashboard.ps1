# Raydium-LP1 — Dashboard HTTP tab (Windows Terminal)
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=== Raydium-LP1 Dashboard ===" -ForegroundColor Cyan
Write-Host "http://${ListenHost}:$Port/  (Funnel, Doctor, settings)" -ForegroundColor Green
Write-Host ""

& (Join-Path $RepoRoot "scripts\run_dashboard_web.ps1") -Port $Port -ListenHost $ListenHost
exit $LASTEXITCODE
