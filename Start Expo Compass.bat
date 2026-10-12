@echo off
rem Expo Compass launcher: start the local program if it is not running, then open the app window.
cd /d "%~dp0"
set PORT=8766

curl.exe -s -o nul http://127.0.0.1:%PORT%/api/ping
if not errorlevel 1 goto open

where pythonw >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3 and try again.
  pause
  exit /b 1
)
start "" pythonw "%~dp0server.py" --port %PORT%

for /l %%i in (1,1,20) do (
  curl.exe -s -o nul http://127.0.0.1:%PORT%/api/ping && goto open
  timeout /t 1 /nobreak >nul
)
echo The Expo Compass local program did not start. Run "python server.py" in this folder to see the error.
pause
exit /b 1

:open
if "%EXPO_NO_WINDOW%"=="1" exit /b 0
start "" msedge --app=http://127.0.0.1:%PORT%/
exit /b 0
