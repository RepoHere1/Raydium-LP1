# One command from your MAIN Windows Terminal tab:
#   cd C:\Users\Taylor\Raydium-LP1
#   .\run_dashboard_stack.ps1
#
# Opens two NEW TABS in the same terminal window (Scanner + Web API), then your browser.
# This tab stays a short "mission control" readout — it does not run the scanner here.
param(
    [string]$Config = "config\settings.json",
    [int]$Interval = 60,
    [int]$ShowRejects = 0,
    [int]$WebPort = 8844,
    [string]$WebHost = "127.0.0.1",
    [switch]$CheckRpc,
    [switch]$WriteReports,
    [switch]$WriteRejections,
    [switch]$SpawnWatcher,
    [switch]$NoSpawnWeb,
    [switch]$UseSeparateWindows,
    [switch]$RunScannerInThisTab
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Split-Path -Parent $ScriptDir)).Path
Set-Location $RepoRoot

$webPs1 = Join-Path $RepoRoot "scripts\run_dashboard_web.ps1"
$scanPs1 = Join-Path $RepoRoot "scripts\run_scan_dashboard.ps1"

if (-not (Test-Path -LiteralPath $scanPs1)) {
    throw "Missing scripts\run_scan_dashboard.ps1 — git pull origin cursor/live-dashboard-web-dee0"
}
if (-not $NoSpawnWeb -and -not (Test-Path -LiteralPath $webPs1)) {
    throw "Missing scripts\run_dashboard_web.ps1 — git pull origin cursor/live-dashboard-web-dee0"
}

$shell = "powershell.exe"
if (Get-Command pwsh -ErrorAction SilentlyContinue) {
    $shell = "pwsh.exe"
}

function Write-StackBanner {
    param([string]$Line, [string]$Color = "White")
    Write-Host $Line -ForegroundColor $Color
}

function Build-ScanTabArguments {
    $args = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
        "-File", $scanPs1,
        "-Config", $Config,
        "-Interval", "$Interval",
        "-ShowRejects", "$ShowRejects"
    )
    if ($CheckRpc) { $args += "-CheckRpc" }
    if ($WriteReports) { $args += "-WriteReports" }
    if ($WriteRejections) { $args += "-WriteRejections" }
    if ($SpawnWatcher) { $args += "-SpawnWatcher" }
    return $args
}

function Start-WebTab {
    param([string]$Mode)
    $webArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
        "-File", $webPs1,
        "-Port", "$WebPort",
        "-ListenHost", $WebHost
    )
    if ($Mode -eq "wt") {
        $wt = Get-Command wt.exe -ErrorAction SilentlyContinue
        if (-not $wt) { throw "wt.exe (Windows Terminal) not found." }
        & wt.exe -w 0 nt --title "LP1 · Web UI" -d $RepoRoot $shell @webArgs | Out-Null
        return
    }
    if ($Mode -eq "window") {
        Start-Process -FilePath $shell -ArgumentList $webArgs -WorkingDirectory $RepoRoot | Out-Null
        return
    }
    throw "Unknown web tab mode: $Mode"
}

function Start-ScanTab {
    param([string]$Mode)
    $scanArgs = Build-ScanTabArguments
    if ($Mode -eq "wt") {
        $wt = Get-Command wt.exe -ErrorAction SilentlyContinue
        if (-not $wt) { throw "wt.exe (Windows Terminal) not found." }
        & wt.exe -w 0 nt --title "LP1 · Scanner" -d $RepoRoot $shell @scanArgs | Out-Null
        return
    }
    if ($Mode -eq "window") {
        Start-Process -FilePath $shell -ArgumentList $scanArgs -WorkingDirectory $RepoRoot | Out-Null
        return
    }
    throw "Unknown scan tab mode: $Mode"
}

Write-Host ""
Write-StackBanner "══════════════════════════════════════════════════════════" "DarkCyan"
Write-StackBanner " Raydium-LP1 · dashboard stack launcher" "Cyan"
Write-StackBanner "══════════════════════════════════════════════════════════" "DarkCyan"
Write-Host ""

function Invoke-ScanScript {
    & $scanPs1 `
        -Config $Config `
        -Interval $Interval `
        -ShowRejects $ShowRejects `
        -CheckRpc:$CheckRpc `
        -WriteReports:$WriteReports `
        -WriteRejections:$WriteRejections `
        -SpawnWatcher:$SpawnWatcher `
        @args
}

if ($RunScannerInThisTab) {
    Write-StackBanner "[INFO] Running scanner in THIS tab (-RunScannerInThisTab)." "Yellow"
    if (-not $NoSpawnWeb) {
        if ($UseSeparateWindows) { Start-WebTab -Mode "window" } else { Start-WebTab -Mode "wt" }
        Start-Sleep -Milliseconds 700
        Start-Process "http://${WebHost}:$WebPort/" | Out-Null
    }
    Invoke-ScanScript
    exit $LASTEXITCODE
}

$tabMode = "window"
if (-not $UseSeparateWindows) {
    if (Get-Command wt.exe -ErrorAction SilentlyContinue) {
        $tabMode = "wt"
    } else {
        Write-StackBanner "[WARN] wt.exe not found — falling back to separate PowerShell windows." "Yellow"
        Write-StackBanner "       Install Windows Terminal or pass -UseSeparateWindows knowingly." "DarkYellow"
        $tabMode = "window"
    }
}

if (-not $NoSpawnWeb) {
    Write-StackBanner "[STEP] Spawning Web API tab ($tabMode) …" "White"
    Start-WebTab -Mode $tabMode
    Start-Sleep -Milliseconds 500
    Write-StackBanner "[STEP] Spawning Scanner tab ($tabMode) …" "White"
    Start-ScanTab -Mode $tabMode
    Start-Sleep -Milliseconds 600
    Write-StackBanner "[STEP] Opening browser …" "White"
    Start-Process "http://${WebHost}:$WebPort/" | Out-Null
    Write-Host ""
    Write-StackBanner "[SUCCESS] Stack is up." "Green"
    Write-Host ""
    Write-StackBanner "── Baby steps (copy boxes in chat use this shape) ──" "Cyan"
    Write-StackBanner "WHERE: Tab «LP1 · Scanner»" "White"
    Write-StackBanner "  DO: Leave it open — scan loop runs here." "White"
    Write-StackBanner "  LOOK FOR: [scan] page 1/N ... then page rollups; after each loop [scan] reloaded config\settings.json ..." "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Tab «LP1 · Web UI»" "White"
    Write-StackBanner "  DO: Leave it open — serves http://${WebHost}:$WebPort/" "White"
    Write-StackBanner "  LOOK FOR: Raydium-LP1 dashboard http://... listening" "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Browser → http://${WebHost}:$WebPort/" "White"
    Write-StackBanner "  DO: Change a field (e.g. hard_exit_min_tvl_usd) → Save settings → disk" "White"
    Write-StackBanner "  LOOK FOR: Green [SUCCESS] banner + settings mtime in gray box" "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Tab «LP1 · Scanner» (again, after save)" "White"
    Write-StackBanner "  DO: Wait for current page batch to finish, then next loop start" "White"
    Write-StackBanner "  LOOK FOR: [scan] reloaded config\settings.json · min_apr=... hard_exit_tvl=..." "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Browser (funnel + shortlist)" "White"
    Write-StackBanner "  DO: Auto-refresh 5s on, or Reload data" "White"
    Write-StackBanner "  LOOK FOR: dash timestamp updates after a full scan (not mid-page)" "Green"
    Write-Host ""
    Write-StackBanner "  This tab = mission control only. Stop: Ctrl+C in Scanner + Web tabs." "DarkYellow"
    Write-Host ""
    exit 0
}

Write-StackBanner "[INFO] -NoSpawnWeb — starting scanner in this tab only." "Yellow"
Invoke-ScanScript
exit $LASTEXITCODE
