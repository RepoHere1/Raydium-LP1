# Hyper-APR discovery: Scanner + Web UI tabs + browser (default).
# Scanner-only (no UI): .\scripts\run_hyper_apr_scan.ps1 -ScannerOnly
param(
    [int]$Interval = 60,
    [int]$ShowRejects = 0,
    [int]$WebPort = 8844,
    [string]$WebHost = "127.0.0.1",
    [switch]$ScannerOnly,
    [switch]$UseSeparateWindows
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$config = Join-Path $repo "config\settings.hyper_apr.json"

if (-not (Test-Path -LiteralPath $config)) {
    throw "Missing $config — git pull origin cursor/live-dashboard-web-dee0"
}

Write-Host ""
Write-Host "=== HYPER-APR (Raydium day.apr, liquid pools) ===" -ForegroundColor Cyan
Write-Host "Config: $config" -ForegroundColor DarkGray
Write-Host "Do NOT paste WHERE / CHECK / LOOK lines into PowerShell." -ForegroundColor Yellow
Write-Host ""

if ($ScannerOnly) {
    Write-Host "[INFO] Scanner only — start Web UI separately: .\scripts\run_dashboard_web.ps1" -ForegroundColor DarkYellow
    & (Join-Path $here "run_scan_dashboard.ps1") -Config $config -Interval $Interval -ShowRejects $ShowRejects @args
    exit $LASTEXITCODE
}

$stackParams = @{
    Config       = $config
    Interval     = $Interval
    ShowRejects  = $ShowRejects
    WebPort      = $WebPort
    WebHost      = $WebHost
}
if ($UseSeparateWindows) { $stackParams["UseSeparateWindows"] = $true }

& (Join-Path $here "run_scan_dashboard_stack.ps1") @stackParams
exit $LASTEXITCODE
