@echo off
echo ============================================
echo INFINITY RESEARCH AI - BACKEND TEST
echo ============================================
cd /d "C:\Users\intel\Music\infinity-research-ai-main\infinity-research-ai-main\backend"
call venv\Scripts\activate.bat

echo.
echo [1/3] Testing offline suite...
python test_research_engine.py

echo.
echo [2/3] Starting backend server...
echo Backend will run on: http://127.0.0.1:8000
echo Swagger docs: http://127.0.0.1:8000/docs
echo.
echo Press Ctrl+C to stop server
uvicorn main:app --reload
