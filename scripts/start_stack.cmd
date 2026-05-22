@echo off
REM One CMD window: looping scanner + dashboard (8844) + /positions.html
cd /d "%~dp0.."
set PYTHONPATH=src
python -m raydium_lp1.web_stack %*
