<#
.SYNOPSIS
  One-shot Raydium-LP1 stack: doctor + scanner + dashboard + monitor (browser when ready).

.DESCRIPTION
  Default: Windows Terminal with 4 tabs (Monitor, Doctor, Scanner, Dashboard).
  Dashboard HTTP starts BEFORE WT tabs so Doctor and browser see a live :8844.
  -SingleWindow: one console (scanner child + HTTP on :8844) via web_stack.

.EXAMPLE
  .\scripts\launch_lp1.ps1
  .\scripts\launch_lp1.ps1 -SingleWindow -NoBrowser
  .\scripts\launch_lp1.ps1 -FreshPort
#>
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1",
    [switch]$SingleWindow,
    [switch]$NoBrowser,
    [switch]$SkipDoctor,
    [switch]$SkipPreflight,
    [switch]$FreshPort,
    [switch]$UseLegacyWindows,
    [switch]$NoDoctorHeal
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

function Get-PyLauncher {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @{ Exe = "py"; Args = @("-3") } }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python not found. Install Python 3.11+ and ensure py or python is on PATH." }
    return @{ Exe = "python"; Args = @() }
}

function Write-Banner {
    Write-Host ""
    Write-Host "  Raydium-LP1 - full stack launcher" -ForegroundColor Cyan
    Write-Host "  Repo: $RepoRoot" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Dashboard:  http://${ListenHost}:$Port/" -ForegroundColor Green
    Write-Host "  Positions:  http://${ListenHost}:$Port/positions.html" -ForegroundColor Green
    Write-Host "  Health:     http://${ListenHost}:$Port/health" -ForegroundColor DarkCyan
    Write-Host ""
}

function Test-ConfigPresent {
    $cfg = Join-Path $RepoRoot "config\settings.json"
    if (-not (Test-Path -LiteralPath $cfg)) {
        Write-Host "WARN  config\settings.json missing - run .\scripts\setup_wizard.ps1" -ForegroundColor Yellow
        return $false
    }
    return $true
}

function Clear-DashboardPort {
    param([int]$PortNum)
    $stop = Join-Path $RepoRoot "scripts\stop_dashboard_port.ps1"
    if (-not (Test-Path -LiteralPath $stop)) { return }
    Write-Host "Clearing stale listeners on port $PortNum ..." -ForegroundColor Cyan
    & $stop -Port $PortNum -ErrorAction SilentlyContinue | Out-Host
    Start-Sleep -Seconds 1
}

Write-Banner
$null = Test-ConfigPresent

Clear-DashboardPort -PortNum $Port
if ($FreshPort) {
    Clear-DashboardPort -PortNum $Port
}

if ($SingleWindow) {
    $py = Get-PyLauncher
    if (-not $SkipPreflight -and -not $SkipDoctor) {
        Write-Host "Preflight: raydium_doctor (one-shot)..." -ForegroundColor Cyan
        $docArgs = @("-m", "raydium_lp1.raydium_doctor", "--advise")
        if ($NoDoctorHeal) { $docArgs += "--no-heal" }
        & $py.Exe @($py.Args + $docArgs)
    }
    Write-Host "Mode: single window (scanner + dashboard on :$Port)" -ForegroundColor Cyan
    $stack = Join-Path $RepoRoot "scripts\start_stack.ps1"
    & $stack --host $ListenHost --port $Port
    exit $LASTEXITCODE
}

$wtScript = Join-Path $RepoRoot "scripts\start_stack_wt.ps1"
if (-not (Test-Path -LiteralPath $wtScript)) {
    throw "Missing stack launcher: $wtScript"
}

$wtParams = @{
    Port       = [int]$Port
    ListenHost = [string]$ListenHost
}
if ($NoBrowser) { $wtParams.NoBrowser = $true }
if ($UseLegacyWindows) { $wtParams.UseLegacyWindows = $true }
if ($NoDoctorHeal) { $wtParams.NoDoctorHeal = $true }
if (-not $SkipPreflight -and -not $SkipDoctor) { $wtParams.RunPreflightDoctor = $true }

Write-Host "Mode: Windows Terminal - Monitor | Doctor | Scanner | Dashboard" -ForegroundColor Cyan
Write-Host "Dashboard starts first; browser opens when /health is OK." -ForegroundColor DarkGray
Write-Host ""

& $wtScript @wtParams
exit $LASTEXITCODE
