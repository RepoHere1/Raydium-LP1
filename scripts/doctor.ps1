param(
    [string]$Config = "config\settings.json"
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

function Show-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    $icon = if ($Ok) { "OK " } else { "BAD" }
    $color = if ($Ok) { "Green" } else { "Yellow" }
    Write-Host "[$icon] $Name $Detail" -ForegroundColor $color
}

Write-Host "Raydium-LP1 doctor" -ForegroundColor Cyan
Show-Check "Repo folder" (Test-Path ".git") (Get-Location).Path
Show-Check "Scanner script" (Test-Path "scripts\scan_raydium_lps.py") "scripts\scan_raydium_lps.py"
Show-Check "Run helper" (Test-Path "scripts\run_scan.ps1") "scripts\run_scan.ps1"
Show-Check "Local settings" (Test-Path $Config) $Config
Show-Check "Local .env" (Test-Path ".env") ".env"

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    Show-Check "Python launcher" $true "py found"
    & py -3 --version
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    Show-Check "Python" ($null -ne $python) "python command"
    if ($python) { & python --version }
}

Write-Host ""
Write-Host "Git remote branches:" -ForegroundColor Cyan
git ls-remote --heads origin 2>$null

Write-Host ""
Write-Host "Settings on Git vs your PC:" -ForegroundColor Cyan
Write-Host "  Git:    config\settings.example.json + config\settings.momentum.example.json"
Write-Host "  Local:  config\settings.json  <-- scanner reads THIS (not in Git)"
Write-Host ""

if (Test-Path $Config) {
    try {
        $cfg = Get-Content $Config -Raw | ConvertFrom-Json
        $momKeys = @(
            "strategy", "min_liquidity_usd", "hard_exit_min_tvl_usd",
            "momentum_enabled", "min_momentum_score", "momentum_hold_hours",
            "momentum_min_volume_tvl_ratio", "momentum_top_hot"
        )
        Write-Host "Momentum-related values in $Config :" -ForegroundColor DarkGray
        foreach ($k in $momKeys) {
            if ($cfg.PSObject.Properties[$k]) {
                Write-Host "  $k = $($cfg.$k)"
            } else {
                Write-Host "  $k = (missing — run .\scripts\sync_settings.ps1)" -ForegroundColor Yellow
            }
        }
    } catch {
        Write-Host "  (could not parse $Config)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  Run: .\scripts\sync_settings.ps1 -ApplyMomentumTemplate" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "If BAD appears for Local settings or Local .env, run:" -ForegroundColor Cyan
Write-Host ".\scripts\setup_wizard.ps1"
Write-Host ".\scripts\sync_settings.ps1 -ApplyMomentumTemplate"
