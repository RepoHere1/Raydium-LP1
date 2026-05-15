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
    [switch]$SpawnWatcher
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

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

if (-not (Test-Path "scripts\scan_raydium_lps.py")) {
    throw "Missing scripts\scan_raydium_lps.py. Your folder does not have the scanner files yet. Pull/copy the Raydium-LP1 files first."
}

if ($SpawnWatcher) {
    $watchPs1 = Join-Path $RepoRoot "scripts\watch_verdict.ps1"
    if (-not (Test-Path -LiteralPath $watchPs1)) {
        throw "Missing scripts\watch_verdict.ps1. Git pull the latest Raydium-LP1, or copy watch_verdict.ps1 into your scripts folder."
    }
    $shell = "powershell.exe"
    if (Get-Command pwsh -ErrorAction SilentlyContinue) {
        $shell = "pwsh.exe"
    }
    Start-Process -FilePath $shell -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $watchPs1
    ) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 600
    if ($Loop) {
        Write-Host "Spawned verdict log watcher in a new window ($shell)." -ForegroundColor Cyan
    } else {
        Write-Host "Spawned verdict log watcher ($shell). Pass -Loop so this window keeps scanning and appending reports\verdict_stream.log." -ForegroundColor Yellow
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
