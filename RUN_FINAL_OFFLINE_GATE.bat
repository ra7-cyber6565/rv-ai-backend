@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Strongest proof that is intentionally OFFLINE and ZERO-COST.
rem This launcher never performs the live/deployed/operator-attestation gates.

set "PYTHON_EXE="
if exist "venv\Scripts\python.exe" set "PYTHON_EXE=venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo ================================================================
echo Infinity Research AI - FINAL OFFLINE GATE
echo This proves offline code/fixture behaviour only.
echo It does NOT claim live or production readiness.
echo ================================================================

"%PYTHON_EXE%" scripts\run_final_offline_gate.py %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo FINAL OFFLINE GATE FAILED. Do not call this build release-ready.
  exit /b %RC%
)

echo.
echo FINAL OFFLINE GATE PASSED.
echo Next proof is still separate: live zero-cost acceptance + deployed acceptance.
exit /b 0
