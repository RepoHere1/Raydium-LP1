# Raydium-LP1 - Dashboard HTTP tab (Windows Terminal)
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1",
    [switch]$AttachOnly
)

$ErrorActionPreference = "Continue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Test-DashboardHealth {
    param([string]$BaseUrl)
    try {
        $h = Invoke-WebRequest -Uri "$BaseUrl/health" -UseBasicParsing -TimeoutSec 4
        return ($h.StatusCode -eq 200)
    } catch {
        return $false
    }
}

$base = "http://${ListenHost}:$Port"

Write-Host "=== Raydium-LP1 Dashboard ===" -ForegroundColor Cyan
Write-Host "$base/  (Funnel, Doctor, settings)" -ForegroundColor Green
Write-Host ""

if ($AttachOnly -and (Test-DashboardHealth -BaseUrl $base)) {
    Write-Host "HTTP server already running (started before this tab)." -ForegroundColor DarkGray
    Write-Host "This tab watches /health. Server logs are in the separate Dashboard window." -ForegroundColor DarkGray
    Write-Host ""
    while ($true) {
        if (Test-DashboardHealth -BaseUrl $base) {
            Write-Host ("[{0}] /health OK" -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor DarkGreen
        } else {
            Write-Host ("[{0}] /health DOWN - restart: .\scripts\run_dashboard_web.ps1" -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor Yellow
        }
        Start-Sleep -Seconds 15
    }
}

& (Join-Path $RepoRoot "scripts\run_dashboard_web.ps1") -Port $Port -ListenHost $ListenHost
exit $LASTEXITCODE
