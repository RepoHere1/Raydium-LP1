@echo off
REM Brainiac LIVE buy — paste pool id + deposit USD
REM   cd C:\Users\Taylor\Raydium-LP1
REM   brainiac_buy.cmd YOUR_POOL_ID 1
REM   brainiac_buy.cmd YOUR_POOL_ID 4
REM Setup once if broken:  powershell -File scripts\brainiac_buy_ready.ps1

cd /d "%~dp0"
if "%~1"=="" (
    echo.
    echo Usage: brainiac_buy.cmd POOL_ID [DEPOSIT_USD]
    echo   Example: brainiac_buy.cmd BSPFA8d9qeZdsTubmS6FvriYadx2mzoi6jesauD6hi4e 1
    echo.
    echo Interactive wizard:  brainiac_wizard.cmd -Live
    echo First-time setup:    powershell -File scripts\brainiac_buy_ready.ps1
    echo.
    exit /b 1
)
set "POOL=%~1"
set "USD=%~2"
if "%USD%"=="" set "USD=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\brainiac_open_wizard.ps1" -Live -PoolId "%POOL%" -DepositUsd %USD% -Yes
exit /b %ERRORLEVEL%
