@echo off
REM Brainiac open wizard
REM   From repo root (after cd):
REM     cd /d C:\Users\Taylor\Raydium-LP1
REM     .\brainiac_wizard.cmd
REM   From any other cmd folder (one line):
REM     cd /d C:\Users\Taylor\Raydium-LP1 && brainiac_wizard.cmd -PoolId YOUR_POOL_ID -DepositUsd 4 -Yes
REM     cd /d C:\Users\Taylor\Raydium-LP1 && brainiac_wizard.cmd -Live
REM     cd /d C:\Users\Taylor\Raydium-LP1 && brainiac_wizard.cmd -Live -PoolId YOUR_POOL_ID -DepositUsd 1
REM   Quick LIVE buy (pool + USD):
REM     brainiac_buy.cmd YOUR_POOL_ID 1
REM   First-time / repair setup:
REM     powershell -File scripts\brainiac_buy_ready.ps1

cd /d "%~dp0"
REM PowerShell requires .\ prefix — this .cmd handles that for you.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\brainiac_open_wizard.ps1" %*
exit /b %ERRORLEVEL%
