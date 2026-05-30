# Raydium-LP1 native dashboard (replaces browser UI at :8844 for daily use).
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"
if (-not $env:PYTHONPATH) { $env:PYTHONPATH = "src" }
& py -3 -m raydium_lp1.dashboard_gui @args
