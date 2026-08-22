@echo off
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
  set "PYTHON=venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

echo Running Infinity Research AI strict offline foundation gate...
"%PYTHON%" scripts\run_foundation_gate.py %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo Offline foundation gate PASS hua.
  echo Live zero-cost benchmark aur final architecture audit alag required gates hain.
) else (
  echo.
  echo Offline foundation gate FAIL hua. Upar failed stages dekho.
)

exit /b %RC%
