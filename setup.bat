@echo off
REM One-time setup: installs Python packages + the browser Playwright needs.
cd /d "%~dp0"
echo ==== Installing Python packages ====
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
echo ==== Installing Chromium for Playwright ====
py -m playwright install chromium
echo.
echo Setup done. You can now run:  run.bat
pause
