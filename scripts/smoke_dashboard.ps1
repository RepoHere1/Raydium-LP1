# Quick smoke test for local dashboard (127.0.0.1:8844).
# Run while dashboard is up: .\scripts\run_dashboard_web.ps1  OR  START_LP1_STACK.bat
param(
    [string]$Base = "http://127.0.0.1:8844",
    [switch]$SkipModeFlip
)

$ErrorActionPreference = "Stop"
$fail = 0

function Test-Url($path, $expectStatus = 200) {
    $url = "$Base$path"
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 8
        if ($r.StatusCode -ne $expectStatus) {
            Write-Host "FAIL  $url -> $($r.StatusCode)" -ForegroundColor Red
            $script:fail++
            return $null
        }
        Write-Host "OK    $url" -ForegroundColor Green
        return $r
    } catch {
        Write-Host "FAIL  $url -> $($_.Exception.Message)" -ForegroundColor Red
        $script:fail++
        return $null
    }
}

function Test-Json($path) {
    $r = Test-Url $path
    if (-not $r) { return $null }
    try {
        return $r.Content | ConvertFrom-Json
    } catch {
        Write-Host "FAIL  $path JSON parse" -ForegroundColor Red
        $script:fail++
        return $null
    }
}

Write-Host ""
Write-Host "Raydium-LP1 dashboard smoke @ $Base" -ForegroundColor Cyan
Write-Host ""

$healthOk = $false
try {
    $h = Invoke-WebRequest -Uri "$Base/health" -UseBasicParsing -TimeoutSec 6
    $rt = Invoke-WebRequest -Uri "$Base/api/runtime" -UseBasicParsing -TimeoutSec 6
    if ($h.StatusCode -eq 200 -and ($h.Content -match "raydium-lp1-dashboard") -and $rt.StatusCode -eq 200) {
        Write-Host "OK    /health + /api/runtime (current dashboard_web)" -ForegroundColor Green
        $hj = $h.Content | ConvertFrom-Json
        $rj = $rt.Content | ConvertFrom-Json
        Write-Host "       mode=$($rj.mode) dry_run=$($rj.dry_run)"
        $feats = @($hj.api_features)
        if ($feats -contains "scan_status") {
            Write-Host "OK    /health lists scan_status (Run scan from dashboard)" -ForegroundColor Green
        } else {
            Write-Host "WARN  /health missing scan_status — restart dashboard (stale python on port 8844)" -ForegroundColor Yellow
            $script:fail++
        }
        $healthOk = $true
    }
} catch {
    # old server or down
}

if (-not $healthOk) {
    Write-Host "WARN  /health missing or old server on port 8844" -ForegroundColor Yellow
    Write-Host "      Stop the old window, then run ONE of:" -ForegroundColor Yellow
    Write-Host "        .\RUN_DASHBOARD.bat" -ForegroundColor Yellow
    Write-Host "        .\scripts\run_dashboard_web.ps1" -ForegroundColor Yellow
    Write-Host "        .\scripts\restart_dashboard.ps1" -ForegroundColor Yellow
    Write-Host "      (Not .\dashboard_web.py — that file is under src\raydium_lp1\)" -ForegroundColor Yellow
}

Test-Url "/" | Out-Null
Test-Url "/positions.html" | Out-Null
Test-Url "/dashboard_client.js" | Out-Null

if ($healthOk) {
    Test-Json "/api/scan/status" | Out-Null
}

$dash = Test-Json "/api/dashboard"
if ($dash) {
    $hasDemo = $null -ne $dash.PSObject.Properties["demo_simulated_trades"]
    $hasLive = $null -ne $dash.PSObject.Properties["live_wallet_capacity"]
    if (-not $hasDemo -or -not $hasLive) {
        Write-Host "WARN  dashboard.json snapshot may be old (re-run scanner with --dashboard)" -ForegroundColor Yellow
    } else {
        Write-Host "OK    dashboard has demo_simulated_trades + live_wallet_capacity" -ForegroundColor Green
    }
}

if (-not $SkipModeFlip) {
    if (-not $healthOk) {
        Write-Host "SKIP  mode flip (need current dashboard_web on port 8844)" -ForegroundColor Yellow
    }
    try {
        if (-not $healthOk) { throw "dashboard not current" }
        $body = '{"mode":"demo"}'
        $r = Invoke-WebRequest -Uri "$Base/api/mode" -Method POST -ContentType "application/json" -Body $body -UseBasicParsing -TimeoutSec 8
        $d = $r.Content | ConvertFrom-Json
        if ($d.mode -ne "demo") { throw "expected demo" }
        Write-Host "OK    POST /api/mode demo" -ForegroundColor Green
        $rt2 = Test-Json "/api/runtime"
        if ($rt2 -and $rt2.mode -ne "demo") {
            Write-Host "FAIL  runtime mode after demo flip" -ForegroundColor Red
            $fail++
        }
    } catch {
        if ($healthOk) {
            Write-Host "FAIL  mode demo: $($_.Exception.Message)" -ForegroundColor Red
            $fail++
        }
    }
}

if ($fail -gt 0) {
    Write-Host ""
    Write-Host "$fail check(s) failed." -ForegroundColor Red
    Write-Host ""
    exit 1
}
Write-Host ""
Write-Host "All smoke checks passed." -ForegroundColor Green
Write-Host ""
exit 0
