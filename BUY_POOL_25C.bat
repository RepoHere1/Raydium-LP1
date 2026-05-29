@echo off
setlocal
cd /d "%~dp0"
echo.
echo  BUY_POOL_25C — LIVE open (fee-guard min deposit), pay-token-only
echo  Default pool: 6dquhnENWL2MeV1VModn4GeERJjHzwuHedaqZoCT3WEq
echo  Requires: mode=live in config\settings.json, wallet funded, reports\latest.json from scan.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_proof_25c.ps1" %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo  Failed exit %ERR%. Fix blockers above, then retry.
  pause
)
exit /b %ERR%
