# Quick sanity check before a 50-page scan. Run from repo root:
#   .\scripts\diagnose_scan.ps1
#   .\scripts\diagnose_scan.ps1 -Live -Pages 2
param(
    [switch]$Live,
    [int]$Pages = 2,
    [int]$PageSize = 100,
    [string]$Config = "config\settings.json"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonExe = "py"
    $pythonPrefixArgs = @("-3")
} else {
    $pythonExe = "python"
    $pythonPrefixArgs = @()
}

$diagArgs = @("scripts\diagnose_scan.py", "--config", $Config)
if ($Live) {
    $diagArgs += @("--live", "--pages", "$Pages", "--page-size", "$PageSize")
}

& $pythonExe @pythonPrefixArgs @diagArgs
exit $LASTEXITCODE
