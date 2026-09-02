@echo off
setlocal

REM ============================================================================
REM  Autostart band karo.
REM
REM  Yeh SIRF Startup folder ki us ek file ko hataata hai jo
REM  INSTALL_AUTOSTART.bat ne banayi thi (RV_AI_BACKEND.cmd). Project ka koi
REM  file, koi data, koi setting isse delete nahi hoti.
REM ============================================================================

set "HOOK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RV_AI_BACKEND.cmd"

if not exist "%HOOK%" (
  echo Autostart pehle se band hai - hataane ke liye kuch nahi mila.
  exit /b 0
)

del "%HOOK%"
if exist "%HOOK%" (
  echo [ERROR] File delete nahi ho saki: %HOOK%
  echo         Ise haath se delete kar do.
  exit /b 1
)

echo Ho gaya. Ab login par backend apne aap nahi chalega.
echo Chalane ke liye jab bhi mann ho: START_BACKEND.bat (ya START_BACKEND_LAN.bat)
exit /b 0
