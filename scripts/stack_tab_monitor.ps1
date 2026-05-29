# Raydium-LP1 - Monitor tab: wait for services, open HTML, periodic health checks
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1",
    [switch]$NoBrowser,
    [int]$PollSeconds = 20
)

$ErrorActionPreference = "Continue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$LogDir = Join-Path $RepoRoot "logs"
$null = New-Item -ItemType Directory -Force -Path $LogDir
$LogPath = Join-Path $LogDir "stack_monitor.log"

function Write-Log {
    param(
        [string]$Msg,
        [string]$Level = "info"
    )
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Msg
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Test-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSec = 4
    )
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)
    } catch {
        return $false
    }
}

$base = "http://${ListenHost}:$Port"
$urls = @(
    @{ Name = "Dashboard"; Url = "$base/" },
    @{ Name = "Positions"; Url = "$base/positions.html" },
    @{ Name = "Stack landing"; Url = "$base/index.html" }
)

Write-Log "=== LP1 stack monitor ==="
Write-Log "Waiting for dashboard at $base/health ..."
$deadline = (Get-Date).AddSeconds(120)
$up = $false
while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk "$base/health") {
        $up = $true
        break
    }
    Start-Sleep -Seconds 2
}

if (-not $up) {
    Write-Log -Msg "Dashboard not up after 120s - check the Dashboard tab for errors." -Level "warn"
} else {
    Write-Log "Dashboard is up."
    if (-not $NoBrowser) {
        Write-Log "Opening browser: Dashboard + Positions (single tab each)"
        Start-Process "$base/"
        Start-Sleep -Milliseconds 500
        Start-Process "$base/positions.html"
    }
}

$failStreak = 0
while ($true) {
    $dashOk = Test-HttpOk "$base/health"
    $docOk = Test-Path -LiteralPath (Join-Path $RepoRoot "reports\doctor_report.json")
    $latestOk = Test-Path -LiteralPath (Join-Path $RepoRoot "reports\latest.json")
    if ($dashOk) {
        $failStreak = 0
    } else {
        $failStreak++
    }

    try {
        $rt = Invoke-RestMethod -Uri "$base/api/runtime" -TimeoutSec 4
        $mode = $rt.mode
        $w = $rt.wallet
        if ($w.configured) {
            Write-Log ("Runtime: mode={0} wallet={1}" -f $mode, $w.address)
        } else {
            Write-Log ("Runtime: mode={0} wallet=not configured" -f $mode)
        }
    } catch {
        Write-Log -Msg "Runtime API unreachable." -Level "warn"
    }

    Write-Log ("Health: dashboard={0} doctor_report={1} latest_scan={2}" -f $dashOk, $docOk, $latestOk)
    if ($failStreak -ge 3) {
        Write-Log -Msg "Dashboard down 3+ checks - restart Dashboard tab or START_LP1_STACK.bat." -Level "warn"
    }
    Start-Sleep -Seconds $PollSeconds
}
