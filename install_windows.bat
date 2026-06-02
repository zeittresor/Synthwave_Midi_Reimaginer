@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Synthwave MIDI Reimaginer GUI v0.2.1 - Setup

echo ============================================================
echo Synthwave MIDI Reimaginer GUI v0.2.1 - Windows Setup
echo ============================================================

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating local virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/4] Local virtual environment already exists.
)

echo [2/4] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

if exist "wheelhouse\*.whl" (
    echo [3/4] Installing dependencies from local wheelhouse ^(offline mode^)...
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links="wheelhouse" -r requirements.txt
) else (
    echo [3/4] Installing dependencies from internet/cache...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
if errorlevel 1 goto :error

echo [4/4] Verifying installation...
".venv\Scripts\python.exe" -c "import numpy, PyQt6; print('OK: numpy + PyQt6 available')"
if errorlevel 1 goto :error

echo.
echo [OK] Setup complete.
echo Start with run_windows.bat
echo.
choice /C YN /N /T 10 /D Y /M "Start GUI now? [Y/n] "
if errorlevel 2 exit /b 0
call run_windows.bat
exit /b 0

:error
echo.
echo [ERROR] Setup failed.
echo Check that Python 3.10+ is installed and available as python or py -3.
pause
exit /b 1
