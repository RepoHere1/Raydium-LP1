# Stop old dashboard on port 8844, start stack tabs + open browser.
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1",
    [switch]$FullStack,
    [switch]$NoBrowser,
    [switch]$NoScanner,
    [switch]$ElevateKill
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Get-Listeners($port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Stop-PortListeners {
    param([int]$port)
    $killed = @()
    $failed = @()
    foreach ($procId in @(Get-Listeners $port)) {
        if (-not $procId) { continue }
        try {
            $p = Get-Process -Id $procId -ErrorAction Stop
            Write-Host "Stopping PID $procId ($($p.ProcessName)) on port $port..."
            Stop-Process -Id $procId -Force -ErrorAction Stop
            $killed += $procId
        } catch {
            # Stop-Process can fail when another user's session owns the process.
            $tk = Start-Process -FilePath "taskkill.exe" -ArgumentList "/F", "/PID", "$procId" -Wait -PassThru -NoNewWindow
            if ($tk.ExitCode -eq 0) {
                Write-Host "  taskkill OK for PID $procId"
                $killed += $procId
            } else {
                Write-Host "  Could not stop PID ${procId}: $($_.Exception.Message)" -ForegroundColor Yellow
                $failed += $procId
            }
        }
    }
    return @{ Killed = $killed; Failed = $failed }
}

$maxAttempts = 5
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    $listeners = @(Get-Listeners $Port)
    if ($listeners.Count -eq 0) { break }
    if ($attempt -gt 1) {
        Write-Host "Port $Port still has $($listeners.Count) listener(s); retry $attempt/$maxAttempts..." -ForegroundColor DarkYellow
    }
    $result = Stop-PortListeners -port $Port
    Start-Sleep -Seconds 2
}

if ($ElevateKill -and @(Get-Listeners $Port).Count -gt 0) {
    Write-Host "Trying elevated stop via stop_dashboard_port.ps1 ..." -ForegroundColor Cyan
    & (Join-Path $repoRoot "scripts\stop_dashboard_port.ps1") -Port $Port -Elevate
    Start-Sleep -Seconds 1
}

$still = @(Get-Listeners $Port)
if ($still.Count -gt 0) {
    Write-Host ""
    Write-Host "WARN: port $Port still in use by PID(s): $($still -join ', ')" -ForegroundColor Yellow
    foreach ($procId in $still) {
        try {
            $p = Get-Process -Id $procId -ErrorAction Stop
            Write-Host "  PID $procId = $($p.ProcessName) (started $($p.StartTime))" -ForegroundColor Yellow
        } catch {
            Write-Host "  PID $procId (process details unavailable)" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "Fix:" -ForegroundColor Cyan
    Write-Host "  1) Close every PowerShell tab titled Dashboard / Monitor / Scanner (stack tabs respawn servers)." -ForegroundColor White
    Write-Host "  2) Re-run this script from an elevated PowerShell if you see 'Access is denied'." -ForegroundColor White
    Write-Host "  3) Or run:  .\scripts\stop_dashboard_port.ps1 -Elevate" -ForegroundColor White
    Write-Host "  4) Or run:  .\scripts\restart_dashboard.ps1 -Port 8845 -ElevateKill" -ForegroundColor White
    Write-Host ""
    exit 1
}

$base = "http://${ListenHost}:$Port"
$ps = "powershell.exe"
$common = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File")

if ($FullStack) {
    Write-Host "Starting full LP1 stack (Monitor, Doctor, Scanner, Dashboard)..." -ForegroundColor Cyan
    & (Join-Path $repoRoot "scripts\start_stack_wt.ps1") -Port $Port -ListenHost $ListenHost
    exit $LASTEXITCODE
}

Write-Host "Starting dashboard + scanner + monitor tabs..." -ForegroundColor Cyan
Start-Process $ps -ArgumentList ($common + @("$repoRoot\scripts\run_dashboard_web.ps1", "-Port", "$Port", "-ListenHost", $ListenHost)) -WorkingDirectory $repoRoot
Start-Sleep -Milliseconds 600

if (-not $NoScanner) {
    Start-Process $ps -ArgumentList ($common + @("$repoRoot\scripts\stack_tab_scanner.ps1")) -WorkingDirectory $repoRoot
    Start-Sleep -Milliseconds 400
}

# Monitor polls only — browser opens here once (avoids duplicate tabs from monitor).
$monitorArgs = @("$repoRoot\scripts\stack_tab_monitor.ps1", "-Port", "$Port", "-ListenHost", $ListenHost, "-NoBrowser")
Start-Process $ps -ArgumentList ($common + $monitorArgs) -WorkingDirectory $repoRoot

Write-Host ""
Write-Host "  Dashboard:  $base/" -ForegroundColor Green
Write-Host "  Positions:  $base/positions.html" -ForegroundColor Green
Write-Host "  Health:     $base/health" -ForegroundColor Cyan
Write-Host ""

function Test-DashboardReady {
    param([string]$BaseUrl)
    try {
        $h = Invoke-WebRequest -Uri "$BaseUrl/health" -UseBasicParsing -TimeoutSec 4
        if ($h.StatusCode -eq 200 -and ($h.Content -match "raydium-lp1-dashboard")) {
            return @{ Ok = $true; Detail = "health OK" }
        }
    } catch { }
    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/api/runtime" -UseBasicParsing -TimeoutSec 4
        if ($r.StatusCode -eq 200) { return @{ Ok = $true; Detail = "api/runtime OK (legacy health missing)" } }
    } catch { }
    return @{ Ok = $false; Detail = "not ready" }
}

if (-not $NoBrowser) {
    Write-Host "Waiting for dashboard (health or /api/runtime)..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds(60)
    $opened = $false
    while ((Get-Date) -lt $deadline) {
        $chk = Test-DashboardReady -BaseUrl $base
        if ($chk.Ok) {
            Write-Host "  $($chk.Detail)" -ForegroundColor Green
            Start-Process "$base/"
            Start-Sleep -Milliseconds 500
            Start-Process "$base/positions.html"
            Write-Host "Opened browser: dashboard + positions (one tab each)." -ForegroundColor Green
            $opened = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $opened) {
        Write-Host "Dashboard not ready — restart Dashboard tab or run: .\RUN_DASHBOARD.bat" -ForegroundColor Yellow
        Write-Host "Old server on 8844 lacks /health — use current scripts\run_dashboard_web.ps1" -ForegroundColor Yellow
    }
} else {
    Write-Host "Browser open skipped (-NoBrowser)." -ForegroundColor DarkGray
}
