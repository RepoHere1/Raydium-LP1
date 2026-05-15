# Tail reports/verdict_stream.log (mirror of PASS/REJECT stream).
#
# Window 1 (keep running):  .\scripts\run_scan.ps1 -Loop -SpawnWatcher
# Window 2 (this file):     .\scripts\watch_verdict.ps1
#   Or from CMD:            scripts\watch_verdict.cmd
#
# Colors: lines containing ESC (ANSI) pass through; otherwise [PASS]/[REJ]/[scan] are colorized.
# Use Windows Terminal + pwsh 7 for best ANSI rendering when the log file keeps color escapes.

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

function Write-VerdictColoredLine([string]$line) {
    if ($null -eq $line) { return }
    if ($line.IndexOf([char]0x1b) -ge 0) {
        Write-Host $line
        return
    }
    if ($line -match '\[PASS\]') {
        Write-Host $line -ForegroundColor Green
    } elseif ($line -match '\[REJ\]') {
        Write-Host $line -ForegroundColor Red
    } elseif ($line -match '^\[scan\]') {
        Write-Host $line -ForegroundColor Cyan
    } elseif ($line -match '^(Raydium page|VERDICT \||\[repeat header|^-{10,})') {
        Write-Host $line -ForegroundColor DarkCyan
    } elseif ($line -match 'objective-engine|Setting pressure|Rejected breakdown') {
        Write-Host $line -ForegroundColor Yellow
    } else {
        Write-Host $line
    }
}

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
        Get-Content -LiteralPath $abs -Wait -Tail $Tail -ErrorAction Stop | ForEach-Object { Write-VerdictColoredLine $_ }
    } catch {
        Write-Host "$(Get-Date -Format o)  Tail ended: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 1
}
