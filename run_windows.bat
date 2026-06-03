@echo off
REM source: https://github.com/zeittresor/Synthwave_Midi_Reimaginer
setlocal EnableExtensions
cd /d "%~dp0"
title Synthwave MIDI Reimaginer GUI

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Local virtual environment not found. Running install_windows.bat first...
    call install_windows.bat
    if errorlevel 1 goto :error
)

echo [INFO] Starting Synthwave MIDI Reimaginer GUI...
".venv\Scripts\python.exe" "app\midi_reimaginer_gui.py"
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo [ERROR] Could not start the GUI.
pause
exit /b 1
