@echo off
REM Start the Raydium-LP1 dashboard (HTTP on 127.0.0.1:8844).
REM Not dashboard_web.py at repo root — use this file or the PowerShell script.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_dashboard_web.ps1" %*
