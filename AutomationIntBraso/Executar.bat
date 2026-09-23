@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Automacao-MpcCopilot.ps1"
exit /b %errorlevel%

