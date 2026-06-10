# set_helius_rpc.ps1 - wire your Helius API key into .env + settings.json
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\set_helius_rpc.ps1 -ApiKey YOUR_HELIUS_KEY
#   powershell -File .\scripts\set_helius_rpc.ps1 -ApiKey "https://mainnet.helius-rpc.com/?api-key=YOUR_KEY"

param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

. (Join-Path $PSScriptRoot "_resolve_python.ps1")
if (-not $ResolvedPythonExe) {
    Write-Host "[!!] Python not found" -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $RepoRoot "src"
& $ResolvedPythonExe @ResolvedPythonArgs scripts\set_helius_rpc.py $ApiKey
exit $LASTEXITCODE
