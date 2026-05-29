# Force-stop every process listening on the dashboard port (default 8844).
param(
    [int]$Port = 8844,
    [switch]$Elevate
)

$ErrorActionPreference = "Continue"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-ListenerPids {
    param([int]$port)
    @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { $_ -and $_ -gt 0 })
}

function Show-Listener {
    param([int]$pid)
    try {
        $p = Get-Process -Id $pid -ErrorAction Stop
        $sess = $p.SessionId
        Write-Host "  PID $pid  $($p.ProcessName)  session=$sess  started=$($p.StartTime)"
    } catch {
        Write-Host "  PID $pid  (cannot read process — likely another user or protected)"
    }
}

$pids = Get-ListenerPids -port $Port
if (-not $pids.Count) {
    Write-Host "Port $Port is free (no LISTENING sockets)." -ForegroundColor Green
    exit 0
}

Write-Host "Port $Port listeners:" -ForegroundColor Cyan
foreach ($procId in $pids) { Show-Listener -pid $procId }

if ($Elevate) {
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\scripts\stop_dashboard_port.ps1`" -Port $Port"
    Write-Host "Requesting elevated stop..." -ForegroundColor Yellow
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait
    $left = Get-ListenerPids -port $Port
    if (-not $left.Count) {
        Write-Host "Port $Port is free." -ForegroundColor Green
        exit 0
    }
    Write-Host "Still blocked by: $($left -join ', ')" -ForegroundColor Red
    exit 1
}

foreach ($procId in $pids) {
    Write-Host "Stopping PID $procId ..."
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "  Stop-Process OK" -ForegroundColor Green
        continue
    } catch {
        Write-Host "  Stop-Process failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    $tk = Start-Process -FilePath "taskkill.exe" -ArgumentList "/F", "/PID", "$procId" -Wait -PassThru -NoNewWindow
    if ($tk.ExitCode -eq 0) {
        Write-Host "  taskkill OK" -ForegroundColor Green
    } else {
        Write-Host "  taskkill failed (exit $($tk.ExitCode)) — try -Elevate or close the PowerShell tab that started the dashboard." -ForegroundColor Red
    }
}

Start-Sleep -Seconds 2
$still = Get-ListenerPids -port $Port
if ($still.Count) {
    Write-Host ""
    Write-Host "Port $Port still in use: $($still -join ', ')" -ForegroundColor Red
    Write-Host ""
    Write-Host "These PIDs often survive taskkill when they run in another session or elevated." -ForegroundColor Yellow
    Write-Host "Try in order:" -ForegroundColor Cyan
    Write-Host "  1) Close every LP1 stack PowerShell tab (Dashboard / Monitor / Scanner)." -ForegroundColor White
    Write-Host "  2) Task Manager -> Details -> End task on those python.exe PIDs." -ForegroundColor White
    Write-Host "  3) Run:  .\scripts\stop_dashboard_port.ps1 -Elevate" -ForegroundColor White
    Write-Host "  4) Or start on another port:  .\scripts\restart_dashboard.ps1 -Port 8845" -ForegroundColor White
    exit 1
}

Write-Host "Port $Port is free." -ForegroundColor Green
exit 0
