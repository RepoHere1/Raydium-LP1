# save_helius_once.ps1 - paste Helius key ONCE, saved forever in .env + settings.json
#
# Usage (easiest):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\save_helius_once.ps1
#
# Or paste key on the command line (stays in .env, not in shell history if you use the file method):
#   powershell -File .\scripts\save_helius_once.ps1 -ApiKey "paste-your-key-here"

param(
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$secretsDir = Join-Path $RepoRoot "secrets"
$keyFile = Join-Path $secretsDir "helius_api_key.txt"

if (-not (Test-Path -LiteralPath $secretsDir)) {
    New-Item -ItemType Directory -Path $secretsDir -Force | Out-Null
}

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    if (-not (Test-Path -LiteralPath $keyFile)) {
        @(
            "# Paste ONLY your Helius API key on the next line (one line, no quotes)."
            "# Get it from: https://dashboard.helius.dev"
            "# Example key shape: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            ""
        ) | Set-Content -Path $keyFile -Encoding UTF8
    }

    Write-Host ""
    Write-Host "Opening Notepad - paste your Helius API key on the blank line, SAVE, CLOSE Notepad." -ForegroundColor Cyan
    Write-Host "File: $keyFile" -ForegroundColor DarkGray
    Write-Host ""
    Start-Process notepad.exe -ArgumentList $keyFile -Wait

    $lines = Get-Content -LiteralPath $keyFile -Encoding UTF8 -ErrorAction SilentlyContinue
    $ApiKey = ($lines | Where-Object { $_ -and ($_ -notmatch '^\s*#') } | Select-Object -First 1)
    if ($ApiKey) { $ApiKey = $ApiKey.Trim().Trim('"').Trim("'") }
}

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    Write-Host "[!!] No key found. Put your key in secrets\helius_api_key.txt and run again." -ForegroundColor Red
    exit 1
}

. (Join-Path $PSScriptRoot "_resolve_python.ps1")
if (-not $ResolvedPythonExe) {
    Write-Host "[!!] Python not found" -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $RepoRoot "src"
& $ResolvedPythonExe @ResolvedPythonArgs scripts\set_helius_rpc.py $ApiKey
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "[OK] Helius saved permanently in .env and config\settings.json" -ForegroundColor Green
Write-Host "     You do NOT need to run this again unless you change keys." -ForegroundColor Green
Write-Host ""
