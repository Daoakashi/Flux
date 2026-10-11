@echo off
rem Lance Flux sans fenetre de console.
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
    echo Flux n'est pas encore installe : double-cliquez d'abord sur installer.bat
    pause
    exit /b 1
)
start "" "venv\Scripts\pythonw.exe" "%~dp0flux.py"
