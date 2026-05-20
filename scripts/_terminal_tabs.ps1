# Shared helpers: open companion processes in Windows Terminal tabs (wt.exe)
# when available, instead of spawning separate top-level console windows.

function Test-WindowsTerminalAvailable {
    return $null -ne (Get-Command wt.exe -ErrorAction SilentlyContinue)
}

function Start-RaydiumDashboardWebTab {
    param([string]$RepoRoot)
    if (-not (Test-WindowsTerminalAvailable)) {
        Write-Host "[hint] Install Windows Terminal (wt.exe on PATH) for dashboard tabs. Or run:" -ForegroundColor Yellow
        Write-Host "  .\scripts\run_dashboard_web.ps1" -ForegroundColor Gray
        return
    }
    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $dashPs1 = Join-Path $root "scripts\open_dashboard_wt.ps1"
    if (-not (Test-Path -LiteralPath $dashPs1)) {
        throw "Missing scripts\open_dashboard_wt.ps1"
    }
    $shellName = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) { "pwsh.exe" } else { "powershell.exe" }
    # wt: new tab, start in repo root, run helper so PYTHONPATH=src is always correct.
    $argLine = "nt -d `"$root`" $shellName -NoProfile -ExecutionPolicy Bypass -NoExit -File `"$dashPs1`""
    try {
        $pinfo = [System.Diagnostics.ProcessStartInfo]::new()
        $pinfo.FileName = (Get-Command wt.exe).Source
        $pinfo.Arguments = $argLine
        $pinfo.UseShellExecute = $true
        [void][System.Diagnostics.Process]::Start($pinfo)
        Write-Host "Opened dashboard in a Windows Terminal tab: http://127.0.0.1:8844/" -ForegroundColor Cyan
    } catch {
        Write-Host "Could not start Windows Terminal tab for dashboard: $_" -ForegroundColor Yellow
        Write-Host "  Run manually: .\scripts\run_dashboard_web.ps1" -ForegroundColor Gray
    }
}

function Start-RaydiumVerdictWatcherTab {
    param([string]$RepoRoot)
    $watchPs1 = Join-Path $RepoRoot "scripts\watch_verdict.ps1"
    if (-not (Test-Path -LiteralPath $watchPs1)) {
        throw "Missing scripts\watch_verdict.ps1"
    }
    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $shellName = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) { "pwsh.exe" } else { "powershell.exe" }
    if (Test-WindowsTerminalAvailable) {
        $argLine = "nt -d `"$root`" $shellName -NoProfile -ExecutionPolicy Bypass -NoExit -File `"$watchPs1`""
        try {
            $pinfo = [System.Diagnostics.ProcessStartInfo]::new()
            $pinfo.FileName = (Get-Command wt.exe).Source
            $pinfo.Arguments = $argLine
            $pinfo.UseShellExecute = $true
            [void][System.Diagnostics.Process]::Start($pinfo)
            Write-Host "Opened verdict log watcher in a Windows Terminal tab." -ForegroundColor Cyan
            return
        } catch {
            Write-Host "wt.exe verdict tab failed: $_" -ForegroundColor Yellow
        }
    }
    Write-Host "[hint] Opening verdict watcher in a separate window." -ForegroundColor Yellow
    Start-Process -FilePath $shellName -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $watchPs1
    ) -WorkingDirectory $root | Out-Null
}
