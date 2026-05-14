# Root shortcut for beginners.
# Run from PowerShell with: .\setup_wizard.ps1
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$RepoRoot\scripts\setup_wizard.ps1" @args
exit $LASTEXITCODE
