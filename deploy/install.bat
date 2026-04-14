@echo off
REM ============================================================
REM  INVENTORY SYSTEM - INSTALLATION SCRIPT
REM  Run this script as Administrator for first-time setup
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo     INVENTORY SYSTEM - INSTALLATION
echo ============================================================
echo.

REM Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Please run this script as Administrator!
    echo         Right-click and select "Run as administrator"
    pause
    exit /b 1
)

REM Set variables
set "APP_DIR=%~dp0.."
set "PYTHON_EXE=python"
set "NSSM_URL=https://nssm.cc/release/nssm-2.24.zip"
set "NSSM_DIR=%APP_DIR%\tools\nssm"

echo [1/6] Checking Python installation...
%PYTHON_EXE% --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo         Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
echo       Python found!

echo.
echo [2/6] Creating virtual environment...
cd /d "%APP_DIR%"
if not exist "venv" (
    %PYTHON_EXE% -m venv venv
    echo       Virtual environment created!
) else (
    echo       Virtual environment already exists.
)

echo.
echo [3/6] Installing Python dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
echo       Dependencies installed!

echo.
echo [4/6] Initializing database...
%PYTHON_EXE% -c "from app.database import engine, Base; from app import models; Base.metadata.create_all(bind=engine); print('       Database initialized!')"

echo.
echo [5/6] Downloading NSSM (Service Manager)...
if not exist "%NSSM_DIR%" (
    mkdir "%NSSM_DIR%"
)
if not exist "%NSSM_DIR%\nssm.exe" (
    echo       Downloading NSSM...
    powershell -Command "Invoke-WebRequest -Uri '%NSSM_URL%' -OutFile '%NSSM_DIR%\nssm.zip'"
    powershell -Command "Expand-Archive -Path '%NSSM_DIR%\nssm.zip' -DestinationPath '%NSSM_DIR%' -Force"
    move "%NSSM_DIR%\nssm-2.24\win64\nssm.exe" "%NSSM_DIR%\nssm.exe"
    rmdir /s /q "%NSSM_DIR%\nssm-2.24"
    del "%NSSM_DIR%\nssm.zip"
    echo       NSSM downloaded!
) else (
    echo       NSSM already installed.
)

echo.
echo [6/6] Installation complete!
echo.
echo ============================================================
echo  NEXT STEPS:
echo ============================================================
echo.
echo  1. Test the app:
echo     Run: deploy\start.bat
echo.
echo  2. Install as Windows Service (auto-start on boot):
echo     Run: deploy\install-service.bat
echo.
echo  3. For Cloudflare Tunnel setup:
echo     Run: deploy\setup-cloudflare.bat
echo.
echo ============================================================
pause
