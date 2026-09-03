@echo off
REM Opens a VISIBLE browser, logs in once, and shows what it detects.
REM Use this the first time to make sure login + green-detection work.
cd /d "%~dp0"
title Spor Istanbul Monitor - TEST
py monitor.py --debug
pause
