# Root shortcut — one command for scanner + web UI:
#   cd C:\Users\Taylor\Raydium-LP1
#   .\run_dashboard_stack.ps1
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$RepoRoot\scripts\run_scan_dashboard_stack.ps1" @args
exit $LASTEXITCODE
