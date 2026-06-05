@echo off
setlocal
cd /d "%~dp0"
echo.
echo  BUY_POOL_1USD_SKEW - LIVE open ~$1 with Dynamic Skew Order + safeguards
echo  Pool: 2LoAqKKfMtcu5azXuqyDY7wLsdXR632qMHtG5SF9wy2X
echo  Strategy: trailing_dynamic_skew (pay SOL/USDC/USDT only, fee guard on)
echo.
echo  Preview first (recommended):
echo    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_skew_1usd.ps1" -PreviewOnly
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_skew_1usd.ps1" %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo  Failed exit %ERR%. Try -PreviewOnly to see fee-guard / readiness blockers.
  pause
)
exit /b %ERR%
