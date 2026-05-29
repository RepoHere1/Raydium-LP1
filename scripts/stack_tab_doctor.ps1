# Raydium-LP1 — Doctor tab (Windows Terminal)
# Heal ON by default; paused when RAYDIUM_LP1_AI_EDIT=1 or .raydium_lp1_ai_edit exists
param(
    [int]$Interval = 60,
    [switch]$NoHeal
)

$ErrorActionPreference = "Continue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"
$env:PYTHONUNBUFFERED = "1"

if ($NoHeal) { $env:RAYDIUM_LP1_DOCTOR_NO_HEAL = "1" }

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $pyExe = "py"; $pyArgs = @("-3") } else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python not found." }
    $pyExe = "python"; $pyArgs = @()
}

Write-Host "=== Raydium-LP1 Doctor ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"
Write-Host "Mode: watch every ${Interval}s | advise=on | file-heal=default-on | :8844 auto-restart=ON" -ForegroundColor DarkGray
Write-Host "  (pause file-heal: RAYDIUM_LP1_AI_EDIT=1 or -NoHeal; pause :8844 heal: RAYDIUM_LP1_DOCTOR_NO_DASHBOARD_HEAL=1)" -ForegroundColor DarkGray
Write-Host ""

$doctorArgs = @("-m", "raydium_lp1.raydium_doctor", "--advise")
if ($NoHeal) { $doctorArgs += "--no-heal" }
& $pyExe @pyArgs @doctorArgs
if ($LASTEXITCODE -ne 0) { Write-Host "Initial doctor pass reported issues (exit $LASTEXITCODE)." -ForegroundColor Yellow }

Write-Host ""
Write-Host "Entering watch loop (Ctrl+C to stop this tab only)..." -ForegroundColor Green
$watchArgs = @("-m", "raydium_lp1.raydium_doctor", "--watch", "--interval", "$Interval", "--advise")
if ($NoHeal) { $watchArgs += "--no-heal" }
& $pyExe @pyArgs @watchArgs
exit $LASTEXITCODE
