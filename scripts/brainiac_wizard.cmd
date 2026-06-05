@echo off
REM Same wizard (from scripts folder):
REM   cd /d C:\Users\Taylor\Raydium-LP1\scripts && brainiac_wizard.cmd -PoolId "YOUR_REAL_POOL_ID" -DepositUsd 4 -Yes

cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0brainiac_open_wizard.ps1" %*
exit /b %ERRORLEVEL%
