@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call install_windows.bat
".venv\Scripts\python.exe" "app\midi_reimaginer_core.py" "examples\test.mid" --out-dir "output" --style synthwave --seed 123456 --bpm 124 --repetition 0.45 --intensity 0.65 --no-mp3
pause
