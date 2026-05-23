# Root shortcut — Window 2 while scanning:
#   cd C:\Users\Taylor\Raydium-LP1
#   .\run_dashboard_web.ps1
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$RepoRoot\scripts\run_dashboard_web.ps1" @args
exit $LASTEXITCODE
