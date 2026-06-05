<#
.SYNOPSIS
  Set lp_active_strategy to Brainiac 80% skew (pay-type settlement) in config/settings.json.

.EXAMPLE
  cd C:\Users\Taylor\Raydium-LP1
  .\scripts\set_brainiac_strategy.ps1
#>
param(
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SettingsPath = Join-Path $RepoRoot "config\settings.json"
$StrategyId = "brainiac_cursor_success_80_skewed_no_escrow"

if (-not (Test-Path $SettingsPath)) {
    Write-Error "Missing $SettingsPath - copy from config/settings.example.json first."
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupPath = "$SettingsPath.bak-$stamp"
Copy-Item -LiteralPath $SettingsPath -Destination $BackupPath -Force
Write-Host "Backup: $BackupPath" -ForegroundColor DarkGray

$raw = Get-Content -LiteralPath $SettingsPath -Raw -Encoding UTF8
$updated = $raw

$updated = [regex]::Replace($updated, '"lp_active_strategy"\s*:\s*"[^"]*"', ('"lp_active_strategy": "' + $StrategyId + '"'))
$updated = [regex]::Replace($updated, '"mode"\s*:\s*"[^"]*"', '"mode": "live"')
$updated = [regex]::Replace($updated, '"dry_run"\s*:\s*(true|false)', '"dry_run": false')

if ($updated -notmatch '"lp_sweep_junk_to_pay_leg"') {
    $needle = '"lp_active_strategy": "' + $StrategyId + '",'
    $insert = $needle + [Environment]::NewLine + '  "lp_sweep_junk_to_pay_leg": true,'
    if ($updated.Contains($needle)) {
        $updated = $updated.Replace($needle, $insert)
    }
}

if ($Preview) {
    Write-Host ""
    Write-Host "--- lp_active_strategy line ---" -ForegroundColor Cyan
    ($updated -split "`n") | Where-Object { $_ -match "lp_active_strategy|lp_sweep_junk|mode|dry_run" }
    Write-Host ""
    Write-Host "(Preview only - settings.json not written)" -ForegroundColor Yellow
    exit 0
}

Set-Content -LiteralPath $SettingsPath -Value $updated -Encoding UTF8 -NoNewline

Write-Host ""
Write-Host "Updated config/settings.json:" -ForegroundColor Green
Write-Host "  lp_active_strategy = $StrategyId"
Write-Host "  mode               = live"
Write-Host "  dry_run            = false"
Write-Host "  lp_sweep_junk_to_pay_leg = true (if was missing)"
Write-Host ""
Write-Host "Next LIVE open:" -ForegroundColor Cyan
Write-Host "  cd /d $RepoRoot"
Write-Host "  .\brainiac_wizard.cmd"
