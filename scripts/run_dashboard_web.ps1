param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonExe = "py"
    $pythonPrefixArgs = @("-3")
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Install Python 3 and check Add python.exe to PATH, then open a new PowerShell window."
    }
    $pythonExe = "python"
    $pythonPrefixArgs = @()
}

Write-Host "Dashboard UI: http://${ListenHost}:$Port/  (localhost only)" -ForegroundColor Cyan
Write-Host "Pair with Window 1: .\scripts\run_scan_dashboard.ps1" -ForegroundColor DarkGray

& $pythonExe @pythonPrefixArgs -c "from raydium_lp1.dashboard_web import main" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "dashboard_web failed to import (SyntaxError?). git pull cursor/live-dashboard-web-dee0 then retry."
}

& $pythonExe @pythonPrefixArgs -m raydium_lp1.dashboard_web --host $ListenHost --port $Port @args
exit $LASTEXITCODE
