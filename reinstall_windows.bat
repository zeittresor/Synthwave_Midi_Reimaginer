@echo off
REM source: https://github.com/zeittresor/Synthwave_Midi_Reimaginer
setlocal EnableExtensions
cd /d "%~dp0"
title Synthwave MIDI Reimaginer GUI - Reinstall

echo This removes the local .venv and installs dependencies again.
choice /C YN /N /M "Continue? [y/N] "
if errorlevel 2 exit /b 0
if exist ".venv" rmdir /s /q ".venv"
call install_windows.bat
