# Root shortcut for beginners.
# Run from PowerShell with: .\run_scan.ps1 -CheckRpc -WriteReports
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$RepoRoot\scripts\run_scan.ps1" @args
exit $LASTEXITCODE
