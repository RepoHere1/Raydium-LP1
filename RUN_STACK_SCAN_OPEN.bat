@echo off
setlocal
cd /d %~dp0

echo Starting local web stack...
start "" powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_stack.ps1

echo Waiting for web server to come up...
timeout /t 5 /nobreak >nul

echo Running scanner...
set "PYTHONPATH=%cd%\src"
python src\raydium_lp1\scanner.py --config config\settings.json

echo Opening positions page...
start "" "http://127.0.0.1:8844/positions.html"

echo Done.
pause >nul
