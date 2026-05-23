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

$script:WtOuterWindowOpened = $false

function Build-ScanTabArguments {
    $scanCliArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
        "-File", $scanPs1,
        "-Config", $Config,
        "-Interval", "$Interval",
        "-ShowRejects", "$ShowRejects"
    )
    if ($CheckRpc) { $scanCliArgs += "-CheckRpc" }
    if ($WriteReports) { $scanCliArgs += "-WriteReports" }
    if ($WriteRejections) { $scanCliArgs += "-WriteRejections" }
    if ($SpawnWatcher) { $scanCliArgs += "-SpawnWatcher" }
    return $scanCliArgs
}

function Start-PowerShellWindow {
    param([string[]]$CliArgs)
    Start-Process -FilePath $shell -ArgumentList $CliArgs -WorkingDirectory $RepoRoot | Out-Null
}

function Invoke-WtHostedTab {
    param(
        [string]$Title,
        [string[]]$CliArgs
    )
    $wt = Get-Command wt.exe -ErrorAction SilentlyContinue
    if (-not $wt) { return $false }

    # Outside Windows Terminal, first spawn needs new-window or tabs land in a hidden MRU window.
    $wtLead = @()
    if ($env:WT_SESSION) {
        $wtLead = @("-w", "0")
    } elseif (-not $script:WtOuterWindowOpened) {
        $wtLead = @("new-window")
        $script:WtOuterWindowOpened = $true
    } else {
        $wtLead = @("-w", "0")
    }

    $wtAll = $wtLead + @(
        "nt",
        "--title", $Title,
        "-d", $RepoRoot,
        $shell
    ) + $CliArgs

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & wt.exe @wtAll 2>&1 | ForEach-Object { Write-Host "  wt: $_" }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($code -ne 0) {
        Write-StackBanner "[WARN] wt.exe exit $code for tab '$Title' — trying separate window." "Yellow"
        return $false
    }
    return $true
}

function Start-WebTab {
    param([string]$Mode)
    $webArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
        "-File", $webPs1,
        "-Port", "$WebPort",
        "-ListenHost", $WebHost,
        "-Settings", $Config
    )
    if ($Mode -eq "wt") {
        if (Invoke-WtHostedTab -Title "LP1 - Web UI" -CliArgs $webArgs) { return }
        Write-StackBanner "[INFO] wt tab failed — opening separate Web UI window." "DarkYellow"
    }
    if ($Mode -eq "wt" -or $Mode -eq "window") {
        Start-PowerShellWindow -CliArgs $webArgs
        return
    }
    throw "Unknown web tab mode: $Mode"
}

function Start-ScanTab {
    param([string]$Mode)
    $scanArgs = Build-ScanTabArguments
    if ($Mode -eq "wt") {
        if (Invoke-WtHostedTab -Title "LP1 - Scanner" -CliArgs $scanArgs) { return }
        Write-StackBanner "[INFO] wt tab failed — opening separate Scanner window." "DarkYellow"
    }
    if ($Mode -eq "wt" -or $Mode -eq "window") {
        Start-PowerShellWindow -CliArgs $scanArgs
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
    Write-StackBanner "  CHECK (do not type into PowerShell): [scan] page 1/N ..." "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Tab LP1 - Web UI (or second window if wt failed)" "White"
    Write-StackBanner "  DO: Leave it open — serves http://${WebHost}:$WebPort/" "White"
    Write-StackBanner "  CHECK: Raydium-LP1 dashboard http://... listening" "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Browser → http://${WebHost}:$WebPort/" "White"
    Write-StackBanner "  DO: Change a field (e.g. hard_exit_min_tvl_usd) → Save settings → disk" "White"
    Write-StackBanner "  CHECK: Green [SUCCESS] banner + settings mtime in gray box" "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Scanner tab (after save)" "White"
    Write-StackBanner "  DO: Wait for next page to start" "White"
    Write-StackBanner "  CHECK: [scan] reloaded config\settings.json · hard_exit_tvl=..." "Green"
    Write-Host ""
    Write-StackBanner "WHERE: Browser (funnel + shortlist)" "White"
    Write-StackBanner "  DO: Auto-refresh 5s on, or Reload data" "White"
    Write-StackBanner "  CHECK: dash timestamp updates after a full scan" "Green"
    Write-Host ""
    Write-StackBanner "No new tabs? Run: .\run_dashboard_stack.ps1 -UseSeparateWindows" "Yellow"
    Write-Host ""
    Write-StackBanner "  This tab = mission control only. Stop: Ctrl+C in Scanner + Web tabs." "DarkYellow"
    Write-Host ""
    exit 0
}

Write-StackBanner "[INFO] -NoSpawnWeb — starting scanner in this tab only." "Yellow"
Invoke-ScanScript
exit $LASTEXITCODE
