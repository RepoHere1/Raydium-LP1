# fix_python_once.ps1 — run ONCE. Finds existing Python, pins it to your user PATH forever.
# Usage (from any folder):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Taylor\Raydium-LP1\scripts\fix_python_once.ps1"

$ErrorActionPreference = "Stop"

function Write-Step([string]$Msg) {
    Write-Host $Msg -ForegroundColor Cyan
}

function Write-Ok([string]$Msg) {
    Write-Host "[OK] $Msg" -ForegroundColor Green
}

function Write-Warn([string]$Msg) {
    Write-Host "[!!] $Msg" -ForegroundColor Yellow
}

function Test-RealPython([string]$ExePath) {
    if (-not (Test-Path -LiteralPath $ExePath)) { return $false }
    $dir = Split-Path -Parent $ExePath
    if ($dir -match "WindowsApps") { return $false }
    try {
        $versionText = & $ExePath --version 2>&1
        if ($LASTEXITCODE -ne 0) { return $false }
        if ($versionText -match "Python (\d+)\.(\d+)") {
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

function Get-PythonVersionTuple([string]$ExePath) {
    try {
        $text = & $ExePath --version 2>&1
        if ($text -match "Python (\d+)\.(\d+)\.(\d+)") {
            return [version]"$($Matches[1]).$($Matches[2]).$($Matches[3])"
        }
        if ($text -match "Python (\d+)\.(\d+)") {
            return [version]"$($Matches[1]).$($Matches[2]).0"
        }
    } catch {}
    return [version]"0.0.0"
}

Write-Host ""
Write-Host "Raydium-LP1 — fix Python PATH once (permanent for your Windows user)" -ForegroundColor White
Write-Host ""

# --- 1) Find every real python.exe on the machine ---
Write-Step "Searching for existing Python installs..."

$searchRoots = @(
    "$env:LOCALAPPDATA\Programs\Python",
    "$env:ProgramFiles\Python*",
    "$env:ProgramFiles(x86)\Python*",
    "C:\Python*",
    "$env:USERPROFILE\anaconda3",
    "$env:USERPROFILE\miniconda3",
    "$env:LOCALAPPDATA\Programs\Microsoft\WindowsApps"
) | Where-Object { $_ -and (Test-Path (Split-Path $_ -Parent -ErrorAction SilentlyContinue) -ErrorAction SilentlyContinue) }

$candidates = New-Object System.Collections.Generic.List[object]

foreach ($root in $searchRoots) {
    Get-ChildItem -Path $root -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue | ForEach-Object {
        if (Test-RealPython $_.FullName) {
            $candidates.Add([pscustomobject]@{
                Path    = $_.FullName
                Dir     = $_.DirectoryName
                Version = Get-PythonVersionTuple $_.FullName
            })
        }
    }
}

# Also check what's already on PATH (in case install is somewhere odd)
foreach ($dir in ($env:Path -split ';' | Where-Object { $_ })) {
    $exe = Join-Path $dir "python.exe"
    if (Test-RealPython $exe) {
        $already = $candidates | Where-Object { $_.Path -eq $exe }
        if (-not $already) {
            $candidates.Add([pscustomobject]@{
                Path    = $exe
                Dir     = $dir
                Version = Get-PythonVersionTuple $exe
            })
        }
    }
}

if ($candidates.Count -eq 0) {
    Write-Warn "No working Python found on this PC."
    Write-Host ""
    Write-Host "Install once (pick ONE):" -ForegroundColor Yellow
    Write-Host '  winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements'
    Write-Host ""
    Write-Host "Or silent installer:" -ForegroundColor Yellow
    Write-Host @'
  $i="$env:TEMP\python-installer.exe"
  Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" -OutFile $i
  Start-Process -Wait -FilePath $i -ArgumentList "/quiet","InstallAllUsers=0","PrependPath=1","Include_launcher=1"
  Remove-Item $i -Force
'@
    Write-Host ""
    Write-Host "Then CLOSE PowerShell, open a NEW window, and run this script again." -ForegroundColor Yellow
    exit 1
}

$best = $candidates | Sort-Object Version -Descending | Select-Object -First 1
$pythonDir = $best.Dir
$scriptsDir = Join-Path $pythonDir "Scripts"
$pythonExe = $best.Path

Write-Ok "Found Python $($best.Version) at $pythonExe"

# --- 2) Permanently prepend to USER Path (works in every folder, every new terminal) ---
Write-Step "Updating your permanent user PATH..."

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }

$parts = $userPath -split ';' | Where-Object { $_ -and $_.Trim() -ne "" }

# Remove old duplicate entries for this python folder
$parts = $parts | Where-Object {
    $_ -ne $pythonDir -and $_ -ne $scriptsDir
}

# Prepend real Python FIRST so it beats Windows Store stubs
$newParts = @($pythonDir)
if (Test-Path -LiteralPath $scriptsDir) {
    $newParts += $scriptsDir
}
$newParts += $parts

$newUserPath = ($newParts -join ";").TrimEnd(";")
[Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")

# Refresh THIS session too
$env:Path = "$pythonDir;$scriptsDir;" + ($env:Path -split ';' | Where-Object {
    $_ -and $_ -ne $pythonDir -and $_ -ne $scriptsDir
} -join ";")

Write-Ok "User PATH updated (permanent). Python is first in line."

# --- 3) Optional: py launcher in same tree ---
$pyLauncher = Join-Path (Split-Path $pythonDir -Parent) "py.exe"
if (-not (Test-Path $pyLauncher)) {
    $pyLauncher = Join-Path $pythonDir "py.exe"
}
if (Test-Path -LiteralPath $pyLauncher) {
    Write-Ok "py launcher found: $pyLauncher"
} else {
    Write-Warn "py launcher not found — use 'python' not 'py' (that's fine)."
}

# --- 4) Verify from a fresh invocation ---
Write-Step "Verifying python works..."
$ver = & $pythonExe --version 2>&1
Write-Ok $ver

Write-Step "Verifying python is found by name (any folder)..."
$which = Get-Command python -ErrorAction SilentlyContinue
if ($which -and $which.Source -notmatch "WindowsApps") {
    Write-Ok "Get-Command python -> $($which.Source)"
} else {
    Write-Warn "python name still points at WindowsApps stub."
    Write-Host "  Do this ONCE manually:" -ForegroundColor Yellow
    Write-Host "  Settings -> Apps -> Advanced app settings -> App execution aliases" -ForegroundColor Yellow
    Write-Host "  Turn OFF: python.exe and python3.exe" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Until then, use the full path (always works):" -ForegroundColor Yellow
    Write-Host "  $pythonExe" -ForegroundColor White
}

# --- 5) Write a tiny helper so Raydium scripts always find Python ---
$helperPath = Join-Path $env:USERPROFILE "python_cmd.txt"
@(
    "PYTHON=$pythonExe"
    "PYTHON_DIR=$pythonDir"
    "FIXED_AT=$(Get-Date -Format o)"
) | Set-Content -Path $helperPath -Encoding UTF8
Write-Ok "Saved helper: $helperPath"

Write-Host ""
Write-Host "DONE. Close this PowerShell window and open a NEW one." -ForegroundColor Green
Write-Host "Then test from ANY folder:" -ForegroundColor Green
Write-Host "  python --version" -ForegroundColor White
Write-Host "  cd C:\Users\Taylor\Raydium-LP1" -ForegroundColor White
Write-Host "  .\run_scan.ps1 -CheckRpc -WriteReports" -ForegroundColor White
Write-Host ""
