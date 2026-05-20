# Shared helpers: open companion processes in Windows Terminal tabs (wt.exe)
# when available, instead of spawning separate top-level console windows.

function Get-RaydiumPythonLaunch {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Exe = "py"; PrefixArgs = @("-3") }
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "Python was not found (py or python). Install Python 3 and retry."
    }
    return @{ Exe = "python"; PrefixArgs = @() }
}

function Test-WindowsTerminalAvailable {
    return $null -ne (Get-Command wt.exe -ErrorAction SilentlyContinue)
}

function Start-RaydiumDashboardWebTab {
    param([string]$RepoRoot)
    $env:PYTHONPATH = "src"
    $py = Get-RaydiumPythonLaunch
    if (Test-WindowsTerminalAvailable) {
        $args = @("-w", "0", "nt", "-d", $RepoRoot, "--title", "Raydium-LP1 dashboard")
        $args += @($py.Exe) + $py.PrefixArgs + @("-m", "raydium_lp1.dashboard_web", "--host", "127.0.0.1", "--port", "8844")
        Start-Process -FilePath "wt.exe" -ArgumentList $args | Out-Null
        Write-Host "Opened dashboard web server in a Windows Terminal tab: http://127.0.0.1:8844/" -ForegroundColor Cyan
    } else {
        Write-Host "[hint] Install Windows Terminal so the dashboard can open in a new tab. Run manually:" -ForegroundColor Yellow
        Write-Host "  `$env:PYTHONPATH='src'; $($py.Exe) $($py.PrefixArgs -join ' ') -m raydium_lp1.dashboard_web" -ForegroundColor Gray
    }
}

function Start-RaydiumVerdictWatcherTab {
    param([string]$RepoRoot)
    $watchPs1 = Join-Path $RepoRoot "scripts\watch_verdict.ps1"
    if (-not (Test-Path -LiteralPath $watchPs1)) {
        throw "Missing scripts\watch_verdict.ps1"
    }
    $shell = "powershell.exe"
    if (Get-Command pwsh -ErrorAction SilentlyContinue) { $shell = "pwsh.exe" }
    if (Test-WindowsTerminalAvailable) {
        $args = @(
            "-w", "0", "nt", "-d", $RepoRoot, "--title", "Raydium-LP1 verdict",
            $shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $watchPs1
        )
        Start-Process -FilePath "wt.exe" -ArgumentList $args | Out-Null
        Write-Host "Opened verdict log watcher in a Windows Terminal tab ($shell)." -ForegroundColor Cyan
    } else {
        Write-Host "[hint] Install Windows Terminal for tabbed verdict tail. Fallback: new window." -ForegroundColor Yellow
        Start-Process -FilePath $shell -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $watchPs1
        ) -WorkingDirectory $RepoRoot | Out-Null
    }
}
