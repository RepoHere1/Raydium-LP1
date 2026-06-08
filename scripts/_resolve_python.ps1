# _resolve_python.ps1 — find a real python.exe on Windows (dot-source from other scripts)
# Sets: $script:ResolvedPythonExe, $script:ResolvedPythonArgs (array)

function Test-RealPythonExe([string]$ExePath) {
    if (-not $ExePath -or -not (Test-Path -LiteralPath $ExePath)) { return $false }
    if ($ExePath -match "WindowsApps") { return $false }
    try {
        $out = & $ExePath --version 2>&1
        return ($LASTEXITCODE -eq 0 -or $out -match "Python \d")
    } catch {
        return $false
    }
}

function Resolve-PythonForLp1 {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps" -and (Test-RealPythonExe $cmd.Source)) {
        return @{ Exe = $cmd.Source; Args = @() }
    }

    $helper = Join-Path $env:USERPROFILE "python_cmd.txt"
    if (Test-Path -LiteralPath $helper) {
        foreach ($line in Get-Content -LiteralPath $helper -Encoding UTF8) {
            if ($line -match "^PYTHON=(.+)$") {
                $p = $Matches[1].Trim()
                if (Test-RealPythonExe $p) {
                    return @{ Exe = $p; Args = @() }
                }
            }
        }
    }

    $searchRoots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python312",
        "$env:ProgramFiles\Python311",
        "$env:ProgramFiles\Python310",
        "C:\Python312",
        "C:\Python311"
    )
    foreach ($root in $searchRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        Get-ChildItem -Path $root -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue | ForEach-Object {
            if (Test-RealPythonExe $_.FullName) {
                return @{ Exe = $_.FullName; Args = @() }
            }
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Exe = $py.Source; Args = @("-3") }
    }

    return $null
}

$found = Resolve-PythonForLp1
if ($found) {
    $script:ResolvedPythonExe = $found.Exe
    $script:ResolvedPythonArgs = $found.Args
} else {
    $script:ResolvedPythonExe = $null
    $script:ResolvedPythonArgs = @()
}
