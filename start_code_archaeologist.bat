@echo off
setlocal
title Code Archaeologist Server
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First-time setup: creating the Python environment...
    py -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create the virtual environment. Ensure Python is installed.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import flask, git, pandas" >nul 2>&1
if errorlevel 1 (
    echo Installing missing project dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency installation failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

echo Starting Code Archaeologist. Your browser will open automatically.
echo Keep this window open while using the application.
".venv\Scripts\python.exe" run.py

echo.
echo The server has stopped.
pause
