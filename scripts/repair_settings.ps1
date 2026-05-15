param(
    [string]$Target = "config\settings.json",
    [switch]$ApplyMomentumTemplate
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$pythonExe = "python"
$pythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
    $pythonArgs = @("-3")
}

$syncArgs = @("-m", "raydium_lp1.settings_sync", "--repair", "--target", $Target)
if ($ApplyMomentumTemplate) {
    $syncArgs += "--momentum"
}

$env:PYTHONPATH = "src"
& $pythonExe @pythonArgs @syncArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Re-run:" -ForegroundColor Cyan
Write-Host "  .\scripts\doctor.ps1"
Write-Host "  .\scripts\run_scan.ps1 -Loop -SpawnWatcher -WriteRejections"
