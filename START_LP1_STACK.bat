@echo off
REM Alias for LAUNCH_LP1.bat (same full stack)
setlocal
cd /d "%~dp0"
call "%~dp0LAUNCH_LP1.bat" %*
if errorlevel 1 (
  echo.
  echo Stack launcher failed. Try: scripts\start_stack_wt.ps1 -UseLegacyWindows
  pause
)
endlocal
