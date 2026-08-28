@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Digital Blue QX5 Microscope
cd /d "%~dp0"

echo ============================================
echo  Digital Blue QX5 Microscope
echo ============================================
echo.

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    set "BOOTSTRAP=python"
    python --version >nul 2>&1
    if errorlevel 1 (
        set "BOOTSTRAP=py -3"
        py -3 --version >nul 2>&1
    )
    if errorlevel 1 (
        echo Python 3 was not found.
        echo.
        echo Install Python 3.10 or newer from https://www.python.org/downloads/
        echo During setup, check "Add python.exe to PATH".
        echo Then run this file again.
        echo.
        pause
        exit /b 1
    )

    echo Creating the repository virtual environment...
    !BOOTSTRAP! -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo Could not create the repository virtual environment.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PYTHON%" (
    echo The repository virtual environment is incomplete.
    echo.
    pause
    exit /b 1
)

echo Installing / updating required packages...
"%VENV_PYTHON%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo Package install failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo Starting the QX5 microscope viewer...
echo.
"%VENV_PYTHON%" "%~dp0src\qx5_gui.py"
if errorlevel 1 (
    echo.
    echo The QX5 viewer exited with an error.
    echo If this is the first time, run install-driver-qx5.bat first.
    echo.
)

pause
