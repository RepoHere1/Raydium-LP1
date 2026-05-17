# ONLY run this file. Do not paste chat lines (WHERE / CHECK / LOOK FOR) into PowerShell.
$ErrorActionPreference = "Stop"
Write-Host ""
Write-Host "Raydium-LP1 START HERE" -ForegroundColor Cyan
Write-Host "  1) This runs a TUNE scan (liquidity sort, no Jupiter hangs)" -ForegroundColor White
Write-Host "  2) Open http://127.0.0.1:8844/ after Web UI tab starts" -ForegroundColor White
Write-Host "  3) Never paste instruction labels into this window" -ForegroundColor Yellow
Write-Host ""
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $here "run_tune_scan.ps1") @args
exit $LASTEXITCODE
