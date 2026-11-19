@echo off
rem Double-click this file to start the YouTube to MP3 Downloader.
rem The first start installs everything needed into the .venv folder.
setlocal
cd /d "%~dp0"

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"

if not defined PY (
    echo Python 3.10 or newer was not found.
    echo.
    echo Please install it from https://www.python.org/downloads/
    echo and then double-click this file again.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

%PY% run_gui.py --detach %*
if errorlevel 1 pause
