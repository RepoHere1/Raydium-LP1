# Shared helpers: open companion processes in Windows Terminal tabs (wt.exe)
# when available, instead of spawning separate top-level console windows.
#
# If you run the scanner *inside* Windows Terminal, WT_SESSION is set and we pass
#   wt -w 0 nt ...   so new tabs attach to THIS window. From classic PowerShell,
#   wt may open a new WT window (first time) — that is expected.

function Get-WtExePath {
    $cmd = Get-Command wt.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    if ($env:LOCALAPPDATA) {
        $apps = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\wt.exe"
        if (Test-Path -LiteralPath $apps) { return $apps }
    }
    $pf = Join-Path ${env:ProgramFiles} "Windows Terminal\wt.exe"
    if (Test-Path -LiteralPath $pf) { return $pf }
    if (${env:ProgramFiles(x86)}) {
        $pf86 = Join-Path ${env:ProgramFiles(x86)} "Windows Terminal\wt.exe"
        if (Test-Path -LiteralPath $pf86) { return $pf86 }
    }
    return $null
}

function Test-WindowsTerminalAvailable {
    return $null -ne (Get-WtExePath)
}

function Build-WtNewTabArgLine {
    param(
        [string]$Root,
        [string]$ShellExe,
        [string]$ShellArgString
    )
    # -w 0: attach new tab to current WT window when WT_SESSION is present (scan run inside WT).
    $leaf = if ($env:WT_SESSION) { "-w 0 nt" } else { "nt" }
    return "$leaf -d `"$Root`" $ShellExe $ShellArgString"
}

function Start-RaydiumDashboardWebTab {
    param([string]$RepoRoot)
    $wt = Get-WtExePath
    if (-not $wt) {
        Write-Host "[hint] wt.exe not found. Web UI: http://127.0.0.1:8844/ — run: .\scripts\run_dashboard_web.ps1" -ForegroundColor Yellow
        return
    }
    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $dashPs1 = Join-Path $root "scripts\open_dashboard_wt.ps1"
    if (-not (Test-Path -LiteralPath $dashPs1)) {
        throw "Missing scripts\open_dashboard_wt.ps1"
    }
    $shellPath = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) {
        (Get-Command pwsh.exe).Source
    } else {
        (Get-Command powershell.exe).Source
    }
    $inner = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$dashPs1`""
    $argLine = Build-WtNewTabArgLine -Root $root -ShellExe "`"$shellPath`"" -ShellArgString $inner
    try {
        $pinfo = [System.Diagnostics.ProcessStartInfo]::new()
        $pinfo.FileName = $wt
        $pinfo.Arguments = $argLine
        $pinfo.UseShellExecute = $true
        [void][System.Diagnostics.Process]::Start($pinfo)
        if ($env:WT_SESSION) {
            Write-Host "Opened dashboard in a new tab (same Windows Terminal): http://127.0.0.1:8844/" -ForegroundColor Cyan
        } else {
            Write-Host "Opened dashboard in Windows Terminal: http://127.0.0.1:8844/ (run scan inside WT for same-window tabs)" -ForegroundColor Cyan
        }
    } catch {
        Write-Host "Could not start Windows Terminal for dashboard: $_" -ForegroundColor Yellow
        Write-Host "  Web UI: http://127.0.0.1:8844/  —  .\scripts\run_dashboard_web.ps1" -ForegroundColor Gray
    }
}

function Start-RaydiumVerdictWatcherTab {
    param([string]$RepoRoot)
    $watchPs1 = Join-Path $RepoRoot "scripts\watch_verdict.ps1"
    if (-not (Test-Path -LiteralPath $watchPs1)) {
        throw "Missing scripts\watch_verdict.ps1"
    }
    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $shellPath = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) {
        (Get-Command pwsh.exe).Source
    } else {
        (Get-Command powershell.exe).Source
    }
    $wt = Get-WtExePath
    if ($wt) {
        $inner = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$watchPs1`""
        $argLine = Build-WtNewTabArgLine -Root $root -ShellExe "`"$shellPath`"" -ShellArgString $inner
        try {
            $pinfo = [System.Diagnostics.ProcessStartInfo]::new()
            $pinfo.FileName = $wt
            $pinfo.Arguments = $argLine
            $pinfo.UseShellExecute = $true
            [void][System.Diagnostics.Process]::Start($pinfo)
            if ($env:WT_SESSION) {
                Write-Host "Opened verdict watcher in a new tab (same Windows Terminal)." -ForegroundColor Cyan
            } else {
                Write-Host "Opened verdict watcher in Windows Terminal (new window if you are not already inside WT)." -ForegroundColor Cyan
            }
            return
        } catch {
            Write-Host "wt.exe verdict launch failed: $_" -ForegroundColor Yellow
        }
    }
    Write-Host "[hint] wt.exe not found — opening verdict watcher in a separate console window." -ForegroundColor Yellow
    Start-Process -FilePath $shellPath -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $watchPs1
    ) -WorkingDirectory $root | Out-Null
}
