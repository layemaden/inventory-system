@echo off
title Inventory Management System
color 0A

echo ================================================
echo   INVENTORY MANAGEMENT SYSTEM
echo ================================================
echo.

cd /d "%~dp0"

REM Check for Python 3.11 or 3.12 (3.14 is not supported)
set PYTHON_CMD=
where py >nul 2>&1
if not errorlevel 1 (
    REM Try py launcher with specific version
    py -3.11 --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=py -3.11
    ) else (
        py -3.12 --version >nul 2>&1
        if not errorlevel 1 (
            set PYTHON_CMD=py -3.12
        )
    )
)

if "%PYTHON_CMD%"=="" (
    echo ERROR: Python 3.11 or 3.12 is required!
    echo.
    echo Python 3.14 is NOT supported by the libraries used in this app.
    echo.
    echo Please install Python 3.11 from:
    echo https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    echo.
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo Using: %PYTHON_CMD%

REM Delete old venv if it exists (might be wrong Python version)
if exist "venv_win\Scripts\activate.bat" (
    echo Checking virtual environment Python version...
    venv_win\Scripts\python.exe --version 2>&1 | findstr "3.14" >nul
    if not errorlevel 1 (
        echo Found Python 3.14 venv, recreating with Python 3.11...
        rmdir /s /q venv_win
    )
)

REM Create venv with Python 3.11
if not exist "venv_win\Scripts\activate.bat" (
    echo Creating virtual environment with Python 3.11...
    %PYTHON_CMD% -m venv venv_win
)

REM Check if uvicorn is installed, if not install dependencies
venv_win\Scripts\python.exe -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies... (this may take a minute)
    venv_win\Scripts\pip.exe install -r requirements.txt
)

REM Create .env if needed
if not exist ".env" (
    copy .env.example .env >nul 2>&1
)

REM Create static directories
if not exist "static\css" mkdir static\css
if not exist "static\js" mkdir static\js

echo.
echo Starting server...
echo.
echo ================================================
echo   URL: http://localhost:8000
echo.
echo   Default Admin: admin / admin123
echo   Default Staff: staff / PIN: 1234
echo.
echo   Press Ctrl+C to stop the server
echo ================================================
echo.

REM Open browser after 3 second delay (runs in background)
start "" powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:8000'"

REM Start the server using venv Python directly
venv_win\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
