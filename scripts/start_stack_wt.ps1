<#
.SYNOPSIS
  Launch Raydium-LP1 as Windows Terminal tabs (Monitor, Doctor, Scanner, Dashboard).
#>
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1",
    [switch]$NoBrowser,
    [switch]$NoDoctorHeal,
    [switch]$UseLegacyWindows
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

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

function Start-LegacySeparateWindows {
    Write-Host "wt.exe not found - using separate console windows." -ForegroundColor Yellow
    $ps = "powershell.exe"
    $common = @("-NoProfile", "-ExecutionPolicy", "Bypass")
    Start-Process $ps -ArgumentList ($common + @("-File", "$RepoRoot\scripts\stack_tab_monitor.ps1", "-Port", $Port, "-ListenHost", $ListenHost)) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 500
    Start-Process $ps -ArgumentList ($common + @("-File", "$RepoRoot\scripts\stack_tab_doctor.ps1")) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 500
    Start-Process $ps -ArgumentList ($common + @("-File", "$RepoRoot\scripts\stack_tab_scanner.ps1")) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 500
    Start-Process $ps -ArgumentList ($common + @("-File", "$RepoRoot\scripts\stack_tab_dashboard.ps1", "-Port", $Port, "-ListenHost", $ListenHost)) -WorkingDirectory $RepoRoot
}

$monitor = Join-Path $RepoRoot "scripts\stack_tab_monitor.ps1"
$doctor  = Join-Path $RepoRoot "scripts\stack_tab_doctor.ps1"
$scanner = Join-Path $RepoRoot "scripts\stack_tab_scanner.ps1"
$dash    = Join-Path $RepoRoot "scripts\stack_tab_dashboard.ps1"

foreach ($f in @($monitor, $doctor, $scanner, $dash)) {
    if (-not (Test-Path -LiteralPath $f)) { throw "Missing stack script: $f" }
}

if ($NoDoctorHeal) { $env:RAYDIUM_LP1_DOCTOR_NO_HEAL = "1" } else { Remove-Item Env:RAYDIUM_LP1_DOCTOR_NO_HEAL -ErrorAction SilentlyContinue }

$wt = Get-WtExecutable
if ($UseLegacyWindows -or -not $wt) {
    Start-LegacySeparateWindows
    exit 0
}

$pshell = "powershell.exe"
$common = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File")

$monitorArgs = @("$monitor", "-Port", "$Port", "-ListenHost", $ListenHost)
if ($NoBrowser) { $monitorArgs += "-NoBrowser" }

$dashArgs = @($dash, "-Port", "$Port", "-ListenHost", $ListenHost)
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
Write-Host "  Dashboard:  http://${ListenHost}:$Port/" -ForegroundColor Green
Write-Host "  Positions:  http://${ListenHost}:$Port/positions.html" -ForegroundColor Green
Write-Host "  Health:     http://${ListenHost}:$Port/health" -ForegroundColor Cyan
Write-Host "  Logs:       logs\stack_monitor.log" -ForegroundColor DarkGray

Start-Process -FilePath $wt -ArgumentList $wtArgs -WorkingDirectory $RepoRoot
exit 0
