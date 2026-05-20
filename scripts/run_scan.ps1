param(
    [string]$Config = "config\settings.json",
    [switch]$Json,
    [switch]$Loop,
    [int]$Interval = 60,
    [switch]$CheckRpc,
    [switch]$WriteReports,
    [switch]$WriteRejections,
    [int]$ShowRejects = 200,
    [switch]$VerdictStdout,
    [string]$VerdictLog = "",
    [switch]$NoVerdictLog,
    [int]$VerdictHeaderEvery = 25,
    [switch]$SpawnWatcher,
    [switch]$SpawnDashboardTab
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot
. (Join-Path $ScriptDir "_terminal_tabs.ps1")

Write-Host "[scan] Web dashboard URL: http://127.0.0.1:8844/  —  .\scripts\run_dashboard_web.ps1  |  auto-tab: -SpawnDashboardTab or `"spawn_dashboard_web`": true in settings." -ForegroundColor Cyan

# Flush Python prints immediately (helps long scans show [REJ] lines live on Windows).
$env:PYTHONUNBUFFERED = "1"

if (-not (Test-Path $Config)) {
    if (Test-Path "config\filters.example.json") {
        Write-Host "Local $Config does not exist yet. Run .\scripts\setup_wizard.ps1 when you are ready." -ForegroundColor Yellow
        Write-Host "Using safe example config for this run." -ForegroundColor Yellow
        $Config = "config\filters.example.json"
    } else {
        throw "Missing config. Run .\scripts\setup_wizard.ps1 first."
    }
}

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonExe = "py"
    $pythonPrefixArgs = @("-3")
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Install Python 3 from https://www.python.org/downloads/windows/ and check Add python.exe to PATH, then open a new PowerShell window and try again."
    }
    $pythonExe = "python"
    $pythonPrefixArgs = @()
}

function Test-SettingsJson([string]$Path) {
    $env:PYTHONPATH = "src"
    $validateArgs = @("-m", "raydium_lp1.settings_sync", "--validate", "--target", $Path)
    & $pythonExe @pythonPrefixArgs @validateArgs
    return $LASTEXITCODE -eq 0
}

if (-not (Test-SettingsJson $Config)) {
    Write-Host ""
    Write-Host "Fix invalid JSON, then re-run. Quick repair (backs up your file):" -ForegroundColor Yellow
    Write-Host "  .\scripts\repair_settings.ps1 -ApplyMomentumTemplate"
    exit 2
}

# Defaults from settings.json — CLI switches always win over these.
try {
    $runScanSettings = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    $runScanSettings = $null
}
if ($null -ne $runScanSettings) {
    if (-not $PSBoundParameters.ContainsKey('Loop')) {
        if ($runScanSettings.scan_loop -eq $true) { $Loop = $true }
    }
    if (-not $PSBoundParameters.ContainsKey('SpawnWatcher')) {
        if ($runScanSettings.spawn_verdict_watcher -eq $true) { $SpawnWatcher = $true }
    }
    if (-not $PSBoundParameters.ContainsKey('SpawnDashboardTab')) {
        if ($runScanSettings.spawn_dashboard_web -eq $true) { $SpawnDashboardTab = $true }
    }
    if (-not $PSBoundParameters.ContainsKey('WriteRejections')) {
        if ($runScanSettings.write_rejections -eq $true) { $WriteRejections = $true }
    }
    if (-not $PSBoundParameters.ContainsKey('Interval')) {
        $iv = $runScanSettings.scan_loop_interval_seconds
        if ($null -ne $iv -and "$iv" -ne "") {
            try {
                $parsed = [int]$iv
                if ($parsed -ge 3 -and $parsed -le 86400) { $Interval = $parsed }
            } catch {}
        }
    }
}
if ($Interval -lt 3) { $Interval = 3 }
if ($Interval -gt 86400) { $Interval = 86400 }

if (-not (Test-Path "scripts\scan_raydium_lps.py")) {
    throw "Missing scripts\scan_raydium_lps.py. Your folder does not have the scanner files yet. Pull/copy the Raydium-LP1 files first."
}

if ($SpawnDashboardTab) {
    try {
        Start-RaydiumDashboardWebTab -RepoRoot $RepoRoot
        Start-Sleep -Milliseconds 500
    } catch {
        Write-Host "Dashboard tab spawn skipped: $_" -ForegroundColor Yellow
    }
}

if ($SpawnWatcher) {
    Start-RaydiumVerdictWatcherTab -RepoRoot $RepoRoot
    Start-Sleep -Milliseconds 600
    $verdictLogPath = Join-Path $RepoRoot "reports\verdict_stream.log"
    if ($Loop) {
        Write-Host "[scan] Verdict watcher started in Windows Terminal (new tab). Tail: $verdictLogPath" -ForegroundColor Cyan
    } else {
        Write-Host "[scan] Verdict watcher started. Pass -Loop so the scan keeps appending: $verdictLogPath" -ForegroundColor Yellow
    }
}

$scannerArgs = @("scripts\scan_raydium_lps.py", "--config", $Config)
if ($Json) {
    $scannerArgs += "--json"
}
if ($Loop) {
    $scannerArgs += @("--loop", "--interval", $Interval)
}
if ($CheckRpc) {
    $scannerArgs += "--check-rpc"
}
if ($WriteReports) {
    $scannerArgs += "--write-reports"
}
if ($WriteRejections) {
    $scannerArgs += "--write-rejections"
}
if ($VerdictStdout) {
    $scannerArgs += "--verdict-stdout"
}
if ($VerdictLog) {
    $scannerArgs += @("--verdict-log", $VerdictLog)
}
if ($NoVerdictLog) {
    $scannerArgs += "--no-verdict-log"
}
if ($VerdictHeaderEvery -ne 25) {
    $scannerArgs += @("--verdict-header-every", "$VerdictHeaderEvery")
}
$scannerArgs += @("--show-rejects", "$ShowRejects")

& $pythonExe @pythonPrefixArgs @scannerArgs
exit $LASTEXITCODE
