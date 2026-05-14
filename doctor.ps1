# Root shortcut for beginners.
# Run from PowerShell with: .\doctor.ps1
$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$RepoRoot\scripts\doctor.ps1" @args
exit $LASTEXITCODE
