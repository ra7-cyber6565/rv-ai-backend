@echo off
setlocal
cd /d "%~dp0"

REM ============================================================================
REM  RV AI backend ko Windows me login ke saath apne aap chalao.
REM
REM  Kaam kaise hota hai: Startup folder me ek chhoti .cmd file rakhi jaati hai
REM  jo is folder ka start script chalati hai. Koi admin rights nahi, koi
REM  registry nahi, koi service nahi - hatana bhi ek file delete karna hai
REM  (REMOVE_AUTOSTART.bat).
REM
REM  Use:
REM     INSTALL_AUTOSTART.bat            (default: local - sirf isi PC par)
REM     INSTALL_AUTOSTART.bat lan        (LAN - usi Wi-Fi ka phone bhi)
REM
REM  "lan" ka matlab: backend par login nahi hai, isliye usi Wi-Fi par jo bhi
REM  hai wo use kar sakta hai. Ghar ke Wi-Fi par theek, public Wi-Fi par nahi.
REM  Har login par chalega - isliye "lan" tabhi chuno jab PC ghar par rehta hai.
REM ============================================================================

set "MODE=%1"
if "%MODE%"=="" set "MODE=local"

if /i "%MODE%"=="local" (
  set "TARGET=START_BACKEND.bat"
) else if /i "%MODE%"=="lan" (
  set "TARGET=START_BACKEND_LAN.bat"
) else (
  echo [ERROR] Mode sirf "local" ya "lan" ho sakta hai. Mila: %MODE%
  exit /b 1
)

if not exist "%~dp0%TARGET%" (
  echo [ERROR] %TARGET% is folder me nahi mila.
  exit /b 1
)

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP%" (
  echo [ERROR] Startup folder nahi mila: %STARTUP%
  exit /b 1
)

set "HOOK=%STARTUP%\RV_AI_BACKEND.cmd"

> "%HOOK%" echo @echo off
>>"%HOOK%" echo REM RV AI backend autostart - hatane ke liye REMOVE_AUTOSTART.bat chalao,
>>"%HOOK%" echo REM ya seedha yeh file delete kar do. Mode: %MODE%
>>"%HOOK%" echo cd /d "%~dp0"
>>"%HOOK%" echo call "%~dp0%TARGET%"

if not exist "%HOOK%" (
  echo [ERROR] Autostart file bani nahi.
  exit /b 1
)

echo.
echo Ho gaya. Ab har login par backend apne aap chalega (%MODE% mode).
echo Autostart file: %HOOK%
if /i "%MODE%"=="lan" (
  echo.
  echo [DHYAN] LAN mode: is server par login nahi hai. Public Wi-Fi par PC
  echo         le jaate ho to REMOVE_AUTOSTART.bat chala kar band kar dena.
)
echo.
echo Hatane ke liye: REMOVE_AUTOSTART.bat
exit /b 0
