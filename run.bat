@echo off
setlocal
title Intel Play QX3 Microscope
cd /d "%~dp0"

echo ============================================
echo  Intel Play QX3 Microscope
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    echo.
    echo 1. Install Python 3.10 or newer from https://www.python.org/downloads/
    echo 2. During setup, check "Add python.exe to PATH"
    echo 3. Run this file again.
    echo.
    pause
    exit /b 1
)

echo Installing / updating required packages...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo Package install failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo Starting the microscope viewer...
echo.
python "%~dp0src\qx3_gui.py"
if errorlevel 1 (
    echo.
    echo The viewer exited with an error.
    echo If this is the first time, run install-driver.bat first.
    echo.
)

pause
