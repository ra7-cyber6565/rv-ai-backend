@echo off
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
  set "PYTHON=venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

echo Checking confirmed zero-cost live research prerequisites...
"%PYTHON%" scripts\run_live_zero_cost_gate.py %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo Live gate command completed successfully.
) else if "%RC%"=="2" (
  echo.
  echo Live calls were blocked safely. Configure only confirmed zero-cost credentials.
) else (
  echo.
  echo Live gate ran but one or more release checks failed.
)

exit /b %RC%
