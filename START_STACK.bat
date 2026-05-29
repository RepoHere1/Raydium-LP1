@echo off
REM One console: scanner + dashboard on :8844 (no WT tabs). For full stack use LAUNCH_LP1.bat
cd /d "%~dp0"
set PYTHONPATH=src
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_lp1.ps1" -SingleWindow %*
