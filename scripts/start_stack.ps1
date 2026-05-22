# One window: looping scanner + dashboard (8844) + /positions.html
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction Stop }
& $py.Source -m raydium_lp1.web_stack @args
exit $LASTEXITCODE
