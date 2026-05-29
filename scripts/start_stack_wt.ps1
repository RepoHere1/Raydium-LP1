<#
.SYNOPSIS
  Launch Raydium-LP1 as Windows Terminal tabs (Monitor, Doctor, Scanner, Dashboard).
  Starts the HTTP server BEFORE WT tabs so Doctor/monitor see a live :8844.
#>
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1",
    [switch]$NoBrowser,
    [switch]$NoDoctorHeal,
    [switch]$UseLegacyWindows,
    [switch]$RunPreflightDoctor
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

function Get-WtExecutable {
    $paths = @(
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\wt.exe",
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\Microsoft.WindowsTerminal_8wekyb3d8bbwe\wt.exe"
    )
    foreach ($p in $paths) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $cmd = Get-Command wt -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-ListenerPids {
    param([int]$port)
    @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { $_ -and $_ -gt 0 })
}

function Test-DashboardHealth {
    param([string]$BaseUrl)
    try {
        $h = Invoke-WebRequest -Uri "$BaseUrl/health" -UseBasicParsing -TimeoutSec 4
        if ($h.StatusCode -eq 200) { return $true }
    } catch { }
    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/api/runtime" -UseBasicParsing -TimeoutSec 4
        if ($r.StatusCode -eq 200) { return $true }
    } catch { }
    return $false
}

function Start-DashboardProcess {
    param([int]$PortNum, [string]$HostName)
    $dashScript = Join-Path $RepoRoot "scripts\run_dashboard_web.ps1"
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $RepoRoot -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $dashScript,
        "-Port", "$PortNum", "-ListenHost", $HostName
    ) | Out-Null
}

function Wait-DashboardReady {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSec = 90
    )
    Write-Host "Waiting for dashboard at $BaseUrl/health ..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-DashboardHealth -BaseUrl $BaseUrl) {
            Write-Host "Dashboard is up." -ForegroundColor Green
            return $true
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "Dashboard not ready after ${TimeoutSec}s - check the Dashboard tab/window." -ForegroundColor Yellow
    return $false
}

function Open-DashboardBrowser {
    param([string]$BaseUrl)
    Start-Process "$BaseUrl/"
    Start-Sleep -Milliseconds 500
    Start-Process "$BaseUrl/positions.html"
    Write-Host "Opened browser: Dashboard + Positions." -ForegroundColor Green
}

function Invoke-PreflightDoctor {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $pyExe = "py"; $pyArgs = @("-3") }
    else {
        $py = Get-Command python -ErrorAction SilentlyContinue
        if (-not $py) { return }
        $pyExe = "python"; $pyArgs = @()
    }
    Write-Host "Preflight: raydium_doctor (one-shot, dashboard should be up)..." -ForegroundColor Cyan
    $docArgs = @("-m", "raydium_lp1.raydium_doctor", "--advise")
    if ($NoDoctorHeal) { $docArgs += "--no-heal" }
    & $pyExe @pyArgs @docArgs
}

function Start-LegacySeparateWindows {
    param([bool]$BrowserAlreadyOpened)
    Write-Host "wt.exe not found - using separate console windows." -ForegroundColor Yellow
    $ps = "powershell.exe"
    $common = @("-NoProfile", "-ExecutionPolicy", "Bypass")
    $monitorArgs = @("-File", "$RepoRoot\scripts\stack_tab_monitor.ps1", "-Port", $Port, "-ListenHost", $ListenHost)
    if ($BrowserAlreadyOpened -or $NoBrowser) { $monitorArgs += "-NoBrowser" }
    Start-Process $ps -ArgumentList ($common + $monitorArgs) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 500
    Start-Process $ps -ArgumentList ($common + @("-File", "$RepoRoot\scripts\stack_tab_doctor.ps1")) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 500
    Start-Process $ps -ArgumentList ($common + @("-File", "$RepoRoot\scripts\stack_tab_scanner.ps1")) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 500
    Start-Process $ps -ArgumentList ($common + @("-File", "$RepoRoot\scripts\stack_tab_dashboard.ps1", "-Port", $Port, "-ListenHost", $ListenHost, "-AttachOnly")) -WorkingDirectory $RepoRoot
}

$monitor = Join-Path $RepoRoot "scripts\stack_tab_monitor.ps1"
$doctor  = Join-Path $RepoRoot "scripts\stack_tab_doctor.ps1"
$scanner = Join-Path $RepoRoot "scripts\stack_tab_scanner.ps1"
$dash    = Join-Path $RepoRoot "scripts\stack_tab_dashboard.ps1"

foreach ($f in @($monitor, $doctor, $scanner, $dash)) {
    if (-not (Test-Path -LiteralPath $f)) { throw "Missing stack script: $f" }
}

$stop = Join-Path $RepoRoot "scripts\stop_dashboard_port.ps1"
if (Test-Path -LiteralPath $stop) {
    & $stop -Port $Port -ErrorAction SilentlyContinue | Out-Null
    Start-Sleep -Seconds 1
}

if ($NoDoctorHeal) { $env:RAYDIUM_LP1_DOCTOR_NO_HEAL = "1" } else { Remove-Item Env:RAYDIUM_LP1_DOCTOR_NO_HEAL -ErrorAction SilentlyContinue }

$base = "http://${ListenHost}:$Port"
$alreadyUp = (Get-ListenerPids -port $Port).Count -gt 0
if (-not $alreadyUp) {
    Write-Host "Starting dashboard HTTP server (separate window) ..." -ForegroundColor Cyan
    Start-DashboardProcess -PortNum $Port -HostName $ListenHost
    Start-Sleep -Milliseconds 800
} else {
    Write-Host "Dashboard already listening on :$Port" -ForegroundColor DarkGray
}

$dashReady = Wait-DashboardReady -BaseUrl $base -TimeoutSec 90
$browserOpened = $false
if ($dashReady -and -not $NoBrowser) {
    Open-DashboardBrowser -BaseUrl $base
    $browserOpened = $true
}

if ($RunPreflightDoctor) {
    Invoke-PreflightDoctor
}

$wt = Get-WtExecutable
if ($UseLegacyWindows -or -not $wt) {
    Start-LegacySeparateWindows -BrowserAlreadyOpened $browserOpened
    exit 0
}

$pshell = "powershell.exe"
$common = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File")

$monitorArgs = @("$monitor", "-Port", "$Port", "-ListenHost", $ListenHost)
if ($browserOpened -or $NoBrowser) { $monitorArgs += "-NoBrowser" }

$dashArgs = @($dash, "-Port", "$Port", "-ListenHost", $ListenHost, "-AttachOnly")
$wtSep = ";"

$wtArgs = @("-w", "0")
$wtArgs += @("new-tab", "--title", "Monitor", "-d", $RepoRoot, $pshell) + $common + $monitorArgs
$wtArgs += $wtSep
$wtArgs += @("new-tab", "--title", "Doctor", "-d", $RepoRoot, $pshell) + $common + @($doctor)
$wtArgs += $wtSep
$wtArgs += @("new-tab", "--title", "Scanner", "-d", $RepoRoot, $pshell) + $common + @($scanner)
$wtArgs += $wtSep
$wtArgs += @("new-tab", "--title", "Dashboard", "-d", $RepoRoot, $pshell) + $common + $dashArgs

Write-Host "Launching Windows Terminal (4 tabs): Monitor, Doctor, Scanner, Dashboard" -ForegroundColor Cyan
Write-Host "  Dashboard:  $base/" -ForegroundColor Green
Write-Host "  Positions:  $base/positions.html" -ForegroundColor Green
Write-Host "  Health:     $base/health" -ForegroundColor Cyan
Write-Host "  Logs:       logs\stack_monitor.log" -ForegroundColor DarkGray

Start-Process -FilePath $wt -ArgumentList $wtArgs -WorkingDirectory $RepoRoot
exit 0
