# Launched inside a Windows Terminal tab: run local dashboard_web with correct cwd + PYTHONPATH.
$ErrorActionPreference = "Stop"
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $RepoRoot
$env:PYTHONPATH = "src"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m raydium_lp1.dashboard_web --host 127.0.0.1 --port 8844
} else {
    & python -m raydium_lp1.dashboard_web --host 127.0.0.1 --port 8844
}
