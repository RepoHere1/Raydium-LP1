# Tail reports/verdict_stream.log (plain-text mirror of PASS/REJECT stderr table).
#
# Window 1 (keep running):  .\scripts\run_scan.ps1 -Loop -Interval 120
# Window 2 (this file):     .\scripts\watch_verdict.ps1
#   Or from CMD:            scripts\watch_verdict.cmd
#   Or one-liner:           pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\path\to\Raydium-LP1\scripts\watch_verdict.ps1"
#
# Why "not recognized"? Usually the script file is missing (git pull) or you ran
#   watch_verdict.ps1   without .\   — PowerShell requires .\script.ps1 for local scripts.
#
# Get-Content -Wait can return when the scanner truncates the log at startup; this
# script loops forever and reconnects so Window 2 stays useful across restarts.

param(
    [string]$LogPath = "",
    [int]$InitialWaitSeconds = 120,
    [int]$Tail = 50
)

$ErrorActionPreference = "Continue"
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot = Split-Path -Parent $ScriptDir

if (-not $LogPath) {
    $LogPath = Join-Path $RepoRoot "reports\verdict_stream.log"
}

$abs = [System.IO.Path]::GetFullPath($LogPath)
Write-Host ""
Write-Host "Verdict log tail (Ctrl+C to exit this window):" -ForegroundColor Cyan
Write-Host "  $abs" -ForegroundColor Cyan
Write-Host "If this path is wrong, pass -LogPath 'D:\your\repo\reports\verdict_stream.log'" -ForegroundColor DarkGray
Write-Host ""

while ($true) {
    if (-not (Test-Path -LiteralPath $abs)) {
        Write-Host "$(Get-Date -Format o)  Waiting for log file (start run_scan.ps1 in Window 1)..." -ForegroundColor Yellow
        $deadline = (Get-Date).AddSeconds($InitialWaitSeconds)
        while (-not (Test-Path -LiteralPath $abs) -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 1
        }
        if (-not (Test-Path -LiteralPath $abs)) {
            Write-Host "$(Get-Date -Format o)  Still missing; retrying (scanner not started yet?)..." -ForegroundColor Yellow
            Start-Sleep -Seconds 3
            continue
        }
    }

    Write-Host "$(Get-Date -Format o)  Following new lines (-Wait). If the scanner restarts, we reconnect..." -ForegroundColor Green
    try {
        Get-Content -LiteralPath $abs -Wait -Tail $Tail -ErrorAction Stop
    } catch {
        Write-Host "$(Get-Date -Format o)  Tail ended: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 1
}
