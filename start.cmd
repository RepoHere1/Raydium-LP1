@echo off
REM Spawn the loopback dashboard in a NEW console (this window returns immediately).
REM From repo root in CMD:  start.cmd
REM Extra args pass through, e.g.  start.cmd --port 8855
setlocal EnableExtensions
cd /d "%~dp0"

where python3 >nul 2>&1
if not errorlevel 1 (
  set "PYLINE=python3 -m raydium_lp1.dashboard_web"
  goto :spawn
)
where python >nul 2>&1
if not errorlevel 1 (
  set "PYLINE=python -m raydium_lp1.dashboard_web"
  goto :spawn
)
where py >nul 2>&1
if not errorlevel 1 (
  set "PYLINE=py -3 -m raydium_lp1.dashboard_web"
  goto :spawn
)

echo [start.cmd] No python3, python, or py on PATH. Install Python 3 or fix PATH.
exit /b 1

:spawn
start "Raydium-LP1 dashboard" /D "%CD%" cmd /k "set PYTHONPATH=src && %PYLINE% %*"
exit /b 0
