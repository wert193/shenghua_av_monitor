@echo off
rem Host-side camera proxy: relays the PC webcam/microphone to the PYNQ board.
rem Usage: start_camera_proxy.bat [board-url]
setlocal
chcp 65001 >nul
title Industrial AV Monitor - Camera Proxy
set "BOARD=%~1"
if "%BOARD%"=="" set "BOARD=http://192.168.137.34:8080"
cd /d "%~dp0.."
echo Board target: %BOARD%
where python >nul 2>nul
if errorlevel 1 (
  py -3 tools\camera_proxy.py --board %BOARD%
) else (
  python tools\camera_proxy.py --board %BOARD%
)
echo.
echo Proxy stopped. Press any key to close this window.
pause >nul
