@echo off
REM Starts the 24/7 monitor. Keep this window open.
cd /d "%~dp0"
title Spor Istanbul Monitor
:loop
py monitor.py
echo.
echo Monitor stopped/crashed. Restarting in 30 seconds... (close this window to stop)
timeout /t 30 /nobreak >nul
goto loop
