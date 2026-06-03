@echo off
REM source: https://github.com/zeittresor/Synthwave_Midi_Reimaginer
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Synthwave MIDI Reimaginer GUI v0.2.9 - Build EXE

echo ============================================================
echo Synthwave MIDI Reimaginer GUI v0.2.9 - Windows EXE Build
echo ============================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

echo [1/5] Creating or reusing local virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 goto :error
)

echo [2/5] Installing/updating build requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo [3/5] Cleaning old build folders...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist SynthwaveMidiReimaginerGUI.spec del /q SynthwaveMidiReimaginerGUI.spec

echo [4/5] Building GUI EXE with PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --windowed ^
  --name SynthwaveMidiReimaginerGUI ^
  --add-data "app\styles;app\styles" ^
  --add-data "app\themes;app\themes" ^
  --add-data "app\lang;app\lang" ^
  --add-data "examples;examples" ^
  --hidden-import PyQt6.QtCore ^
  --hidden-import PyQt6.QtGui ^
  --hidden-import PyQt6.QtWidgets ^
  app\midi_reimaginer_gui.py
if errorlevel 1 goto :error

echo [5/5] Copying helpful docs/scripts next to the EXE...
if not exist "dist\SynthwaveMidiReimaginerGUI\docs" mkdir "dist\SynthwaveMidiReimaginerGUI\docs"
if exist README.md copy /y README.md "dist\SynthwaveMidiReimaginerGUI\README.md" >nul
if exist docs\changelog xcopy /e /i /y docs\changelog "dist\SynthwaveMidiReimaginerGUI\docs\changelog" >nul

echo.
echo [OK] Build finished.
echo EXE folder:
echo   %cd%\dist\SynthwaveMidiReimaginerGUI
echo.
echo Start:
echo   dist\SynthwaveMidiReimaginerGUI\SynthwaveMidiReimaginerGUI.exe
echo.
echo Note: The build is --onedir, not --onefile, so modular styles/themes/languages stay bundled safely.
echo The local feedback profile will be saved under dist\SynthwaveMidiReimaginerGUI\app_data\feedback.
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] Build failed.
echo Check the console output above for details.
echo.
pause
exit /b 1
