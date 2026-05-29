param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

# PowerShell has no `PYTHONPATH=src` prefix - set the env var explicitly so `python -m raydium_lp1.*` resolves.
$src = Join-Path $repoRoot "src"
if (Test-Path $src) {
    $env:PYTHONPATH = $src
}

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py -3 -m raydium_lp1.dashboard_web --host $ListenHost --port $Port @args
} else {
    $py = Get-Command python -ErrorAction Stop
    & $py.Source -m raydium_lp1.dashboard_web --host $ListenHost --port $Port @args
}
