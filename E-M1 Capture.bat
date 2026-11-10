@echo off
rem Double-click to start E-M1 Capture on Windows (Wi-Fi only; opens the browser by itself).
rem Remove --allow-write below for a read-only start.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -B -m omcap.server --allow-write
if errorlevel 1 (
  echo.
  echo E-M1 Capture could not start ^(see above^). Installation: README.md
  pause
)
