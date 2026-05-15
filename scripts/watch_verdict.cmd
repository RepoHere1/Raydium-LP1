@echo off
REM Double-click or CMD: tails reports\verdict_stream.log (same as watch_verdict.ps1)
set "HERE=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%watch_verdict.ps1" %*
