@echo off
REM source: https://github.com/zeittresor/Synthwave_Midi_Reimaginer
setlocal EnableExtensions
cd /d "%~dp0"
title Synthwave MIDI Reimaginer GUI - Prepare Wheelhouse

echo ============================================================
echo Downloading wheels for offline reinstall/use on similar Windows/Python setup
echo ============================================================

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

if not exist "wheelhouse" mkdir "wheelhouse"
%PY% -m pip download -r requirements.txt -d wheelhouse
if errorlevel 1 goto :error

echo.
echo [OK] Wheelhouse prepared.
echo Keep the wheelhouse folder next to install_windows.bat for offline installs.
pause
exit /b 0

:error
echo.
echo [ERROR] Wheel download failed.
pause
exit /b 1
