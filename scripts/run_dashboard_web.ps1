param(
    [switch]$Spawn,
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if ($Spawn) {
    $startCmd = Join-Path $repoRoot "start.cmd"
    if (-not (Test-Path -LiteralPath $startCmd)) {
        throw "Missing $startCmd (repo root start.cmd)."
    }
    $dashArgs = @("--host", $ListenHost, "--port", "$Port") + $args
    Start-Process -FilePath $startCmd -WorkingDirectory $repoRoot -ArgumentList $dashArgs
    return
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction Stop }

& $py.Source -m raydium_lp1.dashboard_web --host $ListenHost --port $Port @args
