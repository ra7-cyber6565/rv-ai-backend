@echo off
setlocal

echo ============================================
echo INFINITY RESEARCH AI - BACKEND
echo ============================================

cd /d "C:\Users\intel\Music\infinity-research-ai-main\infinity-research-ai-main\backend"

REM Laptop safety: if .env/environment did not already choose a storage root,
REM use D: for all runtime/model/cache/vector data. Never silently use C:.
if "%INFINITY_DATA_ROOT%"=="" set "INFINITY_DATA_ROOT=D:\InfinityResearchAI"

if not exist "D:\" (
  echo [ERROR] D: drive available nahi hai. Backend start nahi kiya gaya,
  echo         taaki heavy data C: par silently save na ho.
  exit /b 1
)

if not exist "%INFINITY_DATA_ROOT%" mkdir "%INFINITY_DATA_ROOT%"
if errorlevel 1 (
  echo [ERROR] Storage folder create nahi ho saka: %INFINITY_DATA_ROOT%
  exit /b 1
)

echo Storage root: %INFINITY_DATA_ROOT%

call venv\Scripts\activate.bat
if errorlevel 1 (
  echo [ERROR] Python venv activate nahi hua.
  exit /b 1
)

echo.
echo Starting backend server...
echo Backend: http://127.0.0.1:8000
echo Health:  http://127.0.0.1:8000/health
echo Swagger: http://127.0.0.1:8000/docs
echo.
echo Press Ctrl+C to stop server
python -m uvicorn main:app --reload
