# Root shortcut: hyper-APR scanner + web UI + browser
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$RepoRoot\scripts\run_hyper_apr_scan.ps1" @args
exit $LASTEXITCODE
