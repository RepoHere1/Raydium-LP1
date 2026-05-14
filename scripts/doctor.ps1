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
Write-Host "If BAD appears for Local settings or Local .env, run:" -ForegroundColor Cyan
Write-Host ".\scripts\setup_wizard.ps1"
