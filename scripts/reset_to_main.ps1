# Force this clone to match origin/main exactly (drops broken merge state + stray <<<<<< markers).
#
# Safe for normal use because config\settings.json and .env are usually gitignored and stay on disk.
# Any local COMMITED changes on this branch are discarded.
#
# Usage:
#   .\scripts\reset_to_main.ps1          # type RESET to confirm
#   .\scripts\reset_to_main.ps1 -Yes     # no prompt

param([switch]$Yes)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host ""
Write-Host "Will run: git fetch origin && git reset --hard origin/main" -ForegroundColor Yellow
Write-Host "Fixes unmerged files and Python SyntaxError lines that contain Git merge markers like <<<<<<<<< ." -ForegroundColor Yellow
Write-Host "Tracked files match GitHub main. config\settings.json is usually gitignored and kept on disk." -ForegroundColor DarkGray
Write-Host ""

if (-not $Yes) {
    $ans = Read-Host "Type RESET and Enter to continue (anything else aborts)"
    if ($ans -notmatch '^RESET$') {
        Write-Host "Aborted." -ForegroundColor Cyan
        exit 1
    }
}

git fetch origin
if (-not $?) {
    Write-Error "git fetch origin failed."
}
git reset --hard origin/main
if (-not $?) {
    Write-Error "git reset --hard origin/main failed."
}

Write-Host ""
Write-Host "Done. Pull updates with: git pull origin main (not cursor/* branches unless you intend to)." -ForegroundColor Green
Write-Host "Then: .\scripts\doctor.ps1" -ForegroundColor Green
