@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0AutomationRedentor.ps1"
exit /b %errorlevel%

