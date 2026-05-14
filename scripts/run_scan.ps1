param(
    [string]$Config = "config\settings.json",
    [switch]$Json,
    [switch]$Loop,
    [int]$Interval = 60,
    [switch]$CheckRpc,
    [switch]$WriteReports
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

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

& $pythonExe @pythonPrefixArgs @scannerArgs
exit $LASTEXITCODE
