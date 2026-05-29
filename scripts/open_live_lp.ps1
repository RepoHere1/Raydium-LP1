<#
.SYNOPSIS
  Open one small CLMM LP on-chain (LIVE) and append active_positions.json.

.PARAMETER PoolId
  Raydium pool id from reports/latest.json. Default: top candidate.

.PARAMETER SolAmount
  SOL to deposit (human). Default 0.005 (~75c at ~$150/SOL; CLMM min often needs >=0.005).

.EXAMPLE
  .\scripts\export_keypair.ps1
  .\scripts\open_live_lp.ps1

.EXAMPLE
  .\scripts\open_live_lp.ps1 -PoolId "BSPFA8d9qeZdsTubmS6FvriYadx2mzoi6jesauD6hi4e" -SolAmount 0.005
#>
param(
    [string]$PoolId = "",
    [double]$SolAmount = 0.005
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction Stop; $pyExe = "py"; $pyArgs = @("-3") }
else { $pyExe = "python"; $pyArgs = @() }

Write-Host "Candidates in reports/latest.json:" -ForegroundColor Cyan
& $pyExe @pyArgs (Join-Path $RepoRoot "scripts\list_candidates.py")

if (-not $PoolId) {
    $ans = Read-Host "Pool id (Enter = top candidate)"
    if ($ans.Trim()) { $PoolId = $ans.Trim() }
}

Write-Host ""
Write-Host "Opening LIVE CLMM with ${SolAmount} SOL ..." -ForegroundColor Yellow
& $pyExe @pyArgs (Join-Path $RepoRoot "scripts\open_live_lp_cli.py") $PoolId "$SolAmount"
$exit = $LASTEXITCODE
if ($exit -ne 0) { exit $exit }

Write-Host ""
Write-Host "Refresh dashboard data:" -ForegroundColor Cyan
Write-Host "  .\scripts\run_scan.ps1 -WriteReports   # or Run scan now in browser" -ForegroundColor DarkGray
Write-Host "  Get-Content .\active_positions.json" -ForegroundColor DarkGray
