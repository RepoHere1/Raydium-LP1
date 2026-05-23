@echo off
setlocal
cd /d %~dp0
set "PYTHONPATH=%cd%\src"
python src\raydium_lp1\scanner.py --config config\settings.json
pause
