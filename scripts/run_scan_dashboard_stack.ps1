# One command: new window = web UI, this window = scanner loop + dashboard.json
#   cd C:\Users\Taylor\Raydium-LP1
#   .\scripts\run_scan_dashboard_stack.ps1
param(
    [string]$Config = "config\settings.json",
    [int]$Interval = 60,
    [int]$ShowRejects = 0,
    [int]$WebPort = 8844,
    [string]$WebHost = "127.0.0.1",
    [switch]$CheckRpc,
    [switch]$WriteReports,
    [switch]$WriteRejections,
    [switch]$SpawnWatcher,
    [switch]$NoSpawnWeb
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$webPs1 = Join-Path $RepoRoot "scripts\run_dashboard_web.ps1"
$scanPs1 = Join-Path $RepoRoot "scripts\run_scan_dashboard.ps1"

if (-not (Test-Path -LiteralPath $scanPs1)) {
    throw "Missing scripts\run_scan_dashboard.ps1 — git pull origin cursor/live-dashboard-web-dee0"
}
if (-not $NoSpawnWeb -and -not (Test-Path -LiteralPath $webPs1)) {
    throw "Missing scripts\run_dashboard_web.ps1 — git pull origin cursor/live-dashboard-web-dee0"
}

if (-not $NoSpawnWeb) {
    $shell = "powershell.exe"
    if (Get-Command pwsh -ErrorAction SilentlyContinue) {
        $shell = "pwsh.exe"
    }
    Start-Process -FilePath $shell -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-NoExit",
        "-File", $webPs1,
        "-Port", "$WebPort",
        "-ListenHost", $WebHost
    ) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 800
    Write-Host ""
    Write-Host "Spawned web dashboard in a new window ($shell)." -ForegroundColor Cyan
    Write-Host "  Browser: http://${WebHost}:$WebPort/" -ForegroundColor Green
    Write-Host "  This window: scanner loop (reports\dashboard.json each cycle)." -ForegroundColor Cyan
    Write-Host ""
}

& $scanPs1 `
    -Config $Config `
    -Interval $Interval `
    -ShowRejects $ShowRejects `
    -CheckRpc:$CheckRpc `
    -WriteReports:$WriteReports `
    -WriteRejections:$WriteRejections `
    -SpawnWatcher:$SpawnWatcher `
    @args
exit $LASTEXITCODE
