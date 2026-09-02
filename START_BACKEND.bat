@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo INFINITY RESEARCH AI - BACKEND
echo ============================================

REM Laptop safety: if .env/environment did not already choose a storage root,
REM use D: for all runtime/model/cache/vector data. Never silently use C:.
if "%INFINITY_DATA_ROOT%"=="" if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /B /C:"INFINITY_DATA_ROOT=" ".env"`) do set "INFINITY_DATA_ROOT=%%B"
)
if "%INFINITY_DATA_ROOT%"=="" set "INFINITY_DATA_ROOT=D:\InfinityResearchAI"

for %%D in ("%INFINITY_DATA_ROOT%") do set "DATA_DRIVE=%%~dD"
if "%DATA_DRIVE%"=="" (
  echo [ERROR] INFINITY_DATA_ROOT absolute Windows drive path hona chahiye.
  exit /b 1
)

if not exist "%DATA_DRIVE%\" (
  echo [ERROR] Selected data drive available nahi hai. Backend start nahi hua,
  echo         taaki heavy data kisi fallback drive par silently save na ho.
  exit /b 1
)

if not exist "%INFINITY_DATA_ROOT%" mkdir "%INFINITY_DATA_ROOT%"
if errorlevel 1 (
  echo [ERROR] Storage folder create nahi ho saka: %INFINITY_DATA_ROOT%
  exit /b 1
)

echo Storage root: %INFINITY_DATA_ROOT%

if exist "venv\Scripts\python.exe" (
  set "PYTHON=venv\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python nahi mila. Pehle project venv/Python setup karo.
    exit /b 1
  )
  set "PYTHON=python"
)

"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Selected Python start nahi ho saka.
  exit /b 1
)

echo.
echo Starting backend server...
echo Backend: http://127.0.0.1:8000
echo Health:  http://127.0.0.1:8000/health
echo Swagger: http://127.0.0.1:8000/docs
echo.
echo Press Ctrl+C to stop server
"%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
exit /b %ERRORLEVEL%
