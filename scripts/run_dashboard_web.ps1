param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction Stop }

& $py.Source -m raydium_lp1.dashboard_web --host $ListenHost --port $Port @args
