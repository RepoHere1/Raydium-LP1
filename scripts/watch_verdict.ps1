# Tail the verdict mirror log (same table as stderr, without ANSI).
# Run from repo root OR anywhere — the script resolves paths from its location.
#
# Window 1 (continuous scans):  .\scripts\run_scan.ps1 -Loop -Interval 120
# Window 2 (this script):     .\scripts\watch_verdict.ps1
#
# If Get-Content says "path does not exist", you were not in the repo folder
# or the scan had not started yet — this script waits up to 120s for the file.

param(
    [string]$LogPath = "",
    [int]$WaitSeconds = 120,
    [int]$Tail = 50
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

if (-not $LogPath) {
    $LogPath = Join-Path $RepoRoot "reports\verdict_stream.log"
}

$abs = [System.IO.Path]::GetFullPath($LogPath)
Write-Host "Tailing verdict mirror log:" -ForegroundColor Cyan
Write-Host "  $abs" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $abs)) {
    Write-Host "Waiting for file (start .\scripts\run_scan.ps1 in another window)..." -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while (-not (Test-Path -LiteralPath $abs) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
    }
}

if (-not (Test-Path -LiteralPath $abs)) {
    throw "Log not found after ${WaitSeconds}s: $abs"
}

Get-Content -LiteralPath $abs -Wait -Tail $Tail
