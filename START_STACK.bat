@echo off
REM Double-click or run from CMD: one window = scan loop + http://127.0.0.1:8844/
cd /d "%~dp0"
set PYTHONPATH=src
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_stack.ps1" %*
