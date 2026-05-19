# Force pool_type=all in a settings JSON file (fixes Raydium HTTP 500 from poolType=).
param(
    [string]$Config = "config\settings.hyper_apr.json"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
Set-Location $repo
$env:PYTHONPATH = "src"

$py = if (Get-Command py -ErrorAction SilentlyContinue) { @("py", "-3") } else { @("python") }
& @py -c @"
from pathlib import Path
from raydium_lp1.settings_io import repair_settings_file_if_needed, load_settings_json
p = Path(r'$Config')
changed = repair_settings_file_if_needed(p)
print('repaired keys:', changed or '(already OK)')
print('pool_type =', load_settings_json(p).get('pool_type'))
"@

exit $LASTEXITCODE
