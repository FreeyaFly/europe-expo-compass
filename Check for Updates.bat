@echo off
rem Check every fair against its official website and open the report. Changes nothing.
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3 and try again.
  pause
  exit /b 1
)
python tools\check_updates.py
if errorlevel 1 (
  pause
  exit /b 1
)
for /f "delims=" %%f in ('dir /b /o-d reports\check-*.md') do (
  start "" notepad "reports\%%f"
  goto done
)
:done
pause
