@echo off
REM Raydium-LP1 — one double-click starts the full stack (doctor, scanner, dashboard, browser).
REM PowerShell:  .\scripts\launch_lp1.ps1
REM One console: .\scripts\launch_lp1.ps1 -SingleWindow
setlocal
cd /d "%~dp0"
set PYTHONPATH=%cd%\src
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_lp1.ps1" %*
if errorlevel 1 (
  echo.
  echo Launch failed. Try:  .\scripts\launch_lp1.ps1 -UseLegacyWindows
  pause
)
endlocal
