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
    [switch]$NoConfigHotReload
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

if (-not (Test-Path "scripts\scan_raydium_lps.py")) {
    throw "Missing scripts\scan_raydium_lps.py. Your folder does not have the scanner files yet. Pull/copy the Raydium-LP1 files first."
}

if ($SpawnWatcher) {
    $watchPs1 = Join-Path $RepoRoot "scripts\watch_verdict.ps1"
    if (-not (Test-Path -LiteralPath $watchPs1)) {
        throw @"
Missing scripts\watch_verdict.ps1. That file lives on newer branches (e.g. cursor/verdict-watcher-sync-dee0).
From repo root:
  git fetch origin
  git pull origin <branch-with-watch_verdict.ps1>
Or merge main once the PR is merged.
"@
    }
    $watchAbs = [System.IO.Path]::GetFullPath($watchPs1)
    $shellExe = $null
    $pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
    $winPsCmd = Get-Command powershell -ErrorAction SilentlyContinue
    if ($null -ne $pwshCmd -and $pwshCmd.Source) {
        $shellExe = $pwshCmd.Source
    } elseif ($null -ne $winPsCmd -and $winPsCmd.Source) {
        $shellExe = $winPsCmd.Source
    }
    if (-not $shellExe) {
        throw "SpawnWatcher needs pwsh or powershell on PATH (install PowerShell 7 or use Windows PowerShell)."
    }
    # -NoExit: if the watcher errors, the new window stays open so you can read the message.
    $argList = @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $watchAbs
    )
    try {
        $proc = Start-Process -FilePath $shellExe -ArgumentList $argList `
            -WorkingDirectory $RepoRoot -WindowStyle Normal -PassThru -ErrorAction Stop
        Write-Host "Spawned verdict log watcher (PID $($proc.Id)) in a new console: $shellExe" -ForegroundColor Green
        Write-Host "  -File $watchAbs" -ForegroundColor DarkGray
    } catch {
        Write-Host "SpawnWatcher failed: $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
    Write-Host "Tip: pass -Loop on this run so the scanner keeps appending reports\verdict_stream.log." -ForegroundColor Cyan
    Start-Sleep -Milliseconds 600
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
if ($NoConfigHotReload) {
    $scannerArgs += "--no-config-hot-reload"
}
if ($VerdictHeaderEvery -ne 25) {
    $scannerArgs += @("--verdict-header-every", "$VerdictHeaderEvery")
}
$scannerArgs += @("--show-rejects", "$ShowRejects")

& $pythonExe @pythonPrefixArgs @scannerArgs
exit $LASTEXITCODE
