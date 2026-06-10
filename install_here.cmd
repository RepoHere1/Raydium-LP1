@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_here.ps1" %*
if errorlevel 1 exit /b 1
endlocal
