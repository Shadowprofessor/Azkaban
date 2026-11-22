@echo off
rem Double-click this file to start Azkaban (agent + dashboard). Works from any folder.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
echo.
pause
