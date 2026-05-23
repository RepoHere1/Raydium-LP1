$ErrorActionPreference = 'Stop'

$scriptDir = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($scriptDir)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($scriptDir)) {
    $scriptDir = (Get-Location).Path
}

$launcherPy = Join-Path $scriptDir 'launcher.py'
if (-not (Test-Path -LiteralPath $launcherPy)) {
    Write-Host "launcher.py not found: $launcherPy" -ForegroundColor Red
    exit 1
}

$pythonCmd = $null
foreach ($candidate in @('python', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        $pythonCmd = $cmd.Source
        break
    }
}

if (-not $pythonCmd) {
    Write-Host "Python was not found in PATH." -ForegroundColor Red
    exit 1
}

Write-Host "Launching: $launcherPy" -ForegroundColor Cyan
Push-Location $scriptDir
try {
    & $pythonCmd $launcherPy
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
