# Raydium-LP1 — Scanner tab (Windows Terminal): live Raydium data + dashboard JSON
param(
    [string]$Config = "config\settings.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"
$env:PYTHONUNBUFFERED = "1"

$interval = 60
if (Test-Path -LiteralPath $Config) {
    try {
        $cfg = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.scan_loop_interval_seconds) {
            $interval = [int]$cfg.scan_loop_interval_seconds
        }
    } catch { }
}
if ($interval -lt 3) { $interval = 3 }

Write-Host "=== Raydium-LP1 Scanner ===" -ForegroundColor Cyan
Write-Host "Config: $Config | loop interval: ${interval}s | live API + RPC + dashboard JSON" -ForegroundColor DarkGray
Write-Host ""

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $pyExe = "py"; $pyArgs = @("-3") } else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python not found." }
    $pyExe = "python"; $pyArgs = @()
}

$scanArgs = @(
    "-m", "raydium_lp1.scanner",
    "--config", $Config,
    "--loop", "--interval", "$interval",
    "--dashboard", "--reload-config-each-scan",
    "--check-rpc", "--write-reports", "--write-rejections",
    "--show-rejects", "500"
)
& $pyExe @pyArgs @scanArgs
exit $LASTEXITCODE
