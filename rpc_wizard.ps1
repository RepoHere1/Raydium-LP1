# Root shortcut: .\rpc_wizard.ps1
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$RepoRoot\scripts\rpc_wizard.ps1" @args
exit $LASTEXITCODE
