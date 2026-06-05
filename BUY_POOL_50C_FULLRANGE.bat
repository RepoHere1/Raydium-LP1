@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_fullrange_50c.ps1" %*
exit /b %ERRORLEVEL%
