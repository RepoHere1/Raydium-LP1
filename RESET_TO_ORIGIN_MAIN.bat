@echo off
REM Force this repo to match GitHub origin/main exactly (drops broken merges + <<< markers).
REM Skips PowerShell (.ps1) — use if .\scripts\reset_to_main.ps1 is missing while Git is confused.
REM config\settings.json and .env are usually gitignored and stay put.

cd /d "%~dp0"

echo.
echo Repo: %CD%
echo This will run: git fetch origin ; git merge --abort ; git reset --hard origin/main
echo WARNING: tracked files only — see README. Local commits on THIS branch vs main go away.
echo.
set /p _ok="Type YES to continue: "
if /I not "%_ok%"=="YES" (
  echo Aborted.
  exit /b 1
)

git fetch origin
if errorlevel 1 exit /b 1

git merge --abort 2>nul

git reset --hard origin/main
if errorlevel 1 exit /b 1

echo.
echo Done. Run: .\scripts\doctor.ps1 then .\scripts\run_scan.ps1 -Loop ...
echo.
pause
