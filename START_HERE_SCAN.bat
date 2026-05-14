@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_scan.ps1" -CheckRpc -WriteReports
pause
