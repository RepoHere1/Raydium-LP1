<#
.SYNOPSIS
  Interactive Brainiac LIVE open wizard (remembers last answers except pool id).

.DESCRIPTION
  Wires into lp_brainiac_cursor_success + brainiac_open_runner.
  Saves defaults to config/brainiac_wizard_last.json.
  Pool id always prompts with default ENTER_POOL_ADDRESS_HERE.

.EXAMPLE
  cd /d C:\Users\Taylor\Raydium-LP1 && brainiac_wizard.cmd

.EXAMPLE
  cd /d C:\Users\Taylor\Raydium-LP1 && brainiac_wizard.cmd -PoolId "YOUR_REAL_POOL_ID" -DepositUsd 4 -Yes

.EXAMPLE
  cd /d C:\Users\Taylor\Raydium-LP1 && brainiac_wizard.cmd -Live

.EXAMPLE
  cd /d C:\Users\Taylor\Raydium-LP1 && brainiac_wizard.cmd -Live -PoolId "YOUR_REAL_POOL_ID" -DepositUsd 1
#>
param(
    [string]$PoolId = "",
    [double]$DepositUsd = 0,
    [switch]$PreviewOnly,
    [switch]$Yes,
    [switch]$Live,
    [switch]$HelpFields
)

$ErrorActionPreference = "Stop"
# Works whether you run from repo root (.\scripts\...) or from scripts\ (.\brainiac_open_wizard.ps1)
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

. (Join-Path $PSScriptRoot "_resolve_python.ps1")
if (-not $ResolvedPythonExe) {
    Write-Host "[!!] Python not found. Run once:" -ForegroundColor Yellow
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\fix_python_once.ps1`"" -ForegroundColor White
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\brainiac_buy_ready.ps1`"" -ForegroundColor White
    exit 1
}
$pyExe = $ResolvedPythonExe
$pyArgs = $ResolvedPythonArgs

$script = Join-Path $RepoRoot "scripts\brainiac_open_wizard.py"
$argsList = @($script)

if ($HelpFields) {
    & $pyExe @pyArgs $argsList --help-fields
    exit $LASTEXITCODE
}

if ($PoolId) { $argsList += "--pool", $PoolId }
if ($DepositUsd -gt 0) { $argsList += "--deposit-usd", "$DepositUsd" }
if ($Yes) { $argsList += "--yes" }
if ($Live) { $argsList += "--live" }

if ($Live) {
    & $pyExe @pyArgs $argsList
} elseif (-not $PoolId) {
    & $pyExe @pyArgs $argsList
} else {
    & $pyExe @pyArgs $argsList --non-interactive
}

exit $LASTEXITCODE
