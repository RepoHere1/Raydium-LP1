@echo off
REM Paste Helius key once - saved forever. Opens Notepad for you.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\save_helius_once.ps1" %*
exit /b %ERRORLEVEL%
