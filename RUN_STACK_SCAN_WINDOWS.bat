@echo off
setlocal
cd /d %~dp0
set "PYTHONPATH=%cd%\src"

start "Web Stack" cmd /k "python src\raydium_lp1\web_stack.py"
timeout /t 2 /nobreak >nul
start "Scanner" cmd /k "python src\raydium_lp1\scanner.py --config config\settings.json"
timeout /t 2 /nobreak >nul
start "Positions" cmd /k "start http://127.0.0.1:8844/positions.html"