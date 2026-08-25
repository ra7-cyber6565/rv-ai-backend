@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================================
REM  RV AI backend - PC HOST lane (phone/LAN se pahunch)
REM
REM  START_BACKEND.bat sirf 127.0.0.1 par sunta hai, isliye usko phone se nahi
REM  khola ja sakta. Yeh file wahi backend 0.0.0.0 par chalati hai, taaki usi
REM  Wi-Fi ka phone bhi use kar sake.
REM
REM  SAAF BAAT (padhna zaroori):
REM   * Is backend par koi login/password NAHI hai. 0.0.0.0 par chalane ka
REM     matlab: jo bhi tumhaare Wi-Fi/LAN par hai, wo poora backend use kar
REM     sakta hai (tumhaare API quota par).
REM   * Ghar ke apne Wi-Fi par theek hai. Public Wi-Fi (hostel, cafe, college,
REM     hotel) par yeh file MAT chalao.
REM   * Bahar se (mobile data par) chahiye to LAN nahi - Tailscale (private) ya
REM     Cloudflare Tunnel + login lane use karo. Dekho: docs\PC_HOST.md
REM   * --reload jaan-boojh kar nahi hai: wo development ke liye hai aur file
REM     badalte hi server restart kar deta hai (beech ka research mar jaata).
REM ============================================================================

set "RV_PORT=%1"
if "%RV_PORT%"=="" set "RV_PORT=8000"

echo ============================================
echo RV AI BACKEND - PC HOST (LAN)
echo ============================================
echo.
echo [DHYAN] Is server par login nahi hai. Sirf apne ghar ke Wi-Fi par chalao.
echo         Public Wi-Fi par yeh band rakho.
echo.

REM --- Laptop safety: heavy data C: par chupke se na jaye ---------------------
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
  echo [ERROR] Data drive available nahi hai. Backend start nahi hua, taaki
  echo         heavy data kisi fallback drive par silently save na ho.
  exit /b 1
)
if not exist "%INFINITY_DATA_ROOT%" mkdir "%INFINITY_DATA_ROOT%"
if errorlevel 1 (
  echo [ERROR] Storage folder create nahi ho saka: %INFINITY_DATA_ROOT%
  exit /b 1
)
echo Storage root: %INFINITY_DATA_ROOT%

REM --- Python chuno ----------------------------------------------------------
if exist "venv\Scripts\python.exe" (
  set "PYTHON=venv\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python nahi mila. Pehle project venv setup karo.
    exit /b 1
  )
  set "PYTHON=python"
)
"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Selected Python start nahi ho saka.
  exit /b 1
)

REM --- Phone me daalne ke liye URL ------------------------------------------
echo.
echo Phone/browser me in me se apne Wi-Fi ka pata kholo:
for /f "tokens=2 delims=:" %%I in ('ipconfig ^| findstr /C:"IPv4"') do (
  set "IPV4=%%I"
  set "IPV4=!IPV4: =!"
  echo    http://!IPV4!:%RV_PORT%
)
echo.
echo Is PC par:  http://127.0.0.1:%RV_PORT%
echo Health:     http://127.0.0.1:%RV_PORT%/health
echo.
echo Pehli baar Windows Firewall poochhega - "Private networks" par Allow karo.
echo Band karne ke liye: Ctrl+C
echo.

"%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port %RV_PORT%
exit /b %ERRORLEVEL%
