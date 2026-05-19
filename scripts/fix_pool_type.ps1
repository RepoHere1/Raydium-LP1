# Repair common settings mistakes (pool_type blank, empty report paths).
# -ResetScanFilters: restore hyper-APR funnel defaults (optimizer may have raised min_tvl).
param(
    [string]$Config = "config\settings.hyper_apr.json",
    [switch]$ResetScanFilters
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
Set-Location $repo
$env:PYTHONPATH = "src"

$py = if (Get-Command py -ErrorAction SilentlyContinue) { @("py", "-3") } else { @("python") }
$resetFlag = if ($ResetScanFilters) { "True" } else { "False" }
& @py -c @"
from pathlib import Path
from raydium_lp1.settings_io import repair_settings_file_if_needed, load_settings_json, write_settings_json, settings_text_has_git_conflict, read_settings_text
p = Path(r'$Config')
if p.exists() and settings_text_has_git_conflict(read_settings_text(p)):
    print('git conflict markers found — resolving …')
changed = repair_settings_file_if_needed(p)
reset = $resetFlag
if reset:
    s = load_settings_json(p)
    patch = {
        'min_apr': 50,
        'min_liquidity_usd': 250000,
        'min_volume_24h_usd': 5000,
        'hard_exit_min_tvl_usd': 0,
        'settings_optimizer_auto_apply': False,
        'scan_hyper_apr_mode': True,
        'pool_type': 'all',
    }
    merged = {**s, **patch}
    write_settings_json(p, merged)
    changed = sorted(set(changed) | set(patch))
print('repaired keys:', changed or '(already OK)')
s = load_settings_json(p)
print('pool_type =', s.get('pool_type'))
print('liquidity_history_path =', s.get('liquidity_history_path'))
print('hard_exit_min_tvl_usd =', s.get('hard_exit_min_tvl_usd'))
print('min_liquidity_usd =', s.get('min_liquidity_usd'))
print('settings_optimizer_auto_apply =', s.get('settings_optimizer_auto_apply'))
"@

exit $LASTEXITCODE
