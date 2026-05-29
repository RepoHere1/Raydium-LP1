@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: SWAP_TO_SOL.bat ^<TOKEN_MINT^> [preview]
  echo Example: SWAP_TO_SOL.bat CpEVyS9ec3BmF1vrrVWhnn3FgCPqK48ReWTZXor7pump preview
  exit /b 1
)
set "PYTHONPATH=%cd%\src"
if /i "%~2"=="preview" (
  python scripts\swap_token_to_sol.py %1 --preview-only
) else (
  python scripts\swap_token_to_sol.py %1
)
exit /b %ERRORLEVEL%
