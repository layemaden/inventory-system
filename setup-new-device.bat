@echo off
REM ============================================================
REM  INVENTORY SYSTEM - COMPLETE SETUP FOR NEW DEVICE
REM  Run this script as Administrator on a fresh Windows machine
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo     INVENTORY SYSTEM - NEW DEVICE SETUP
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

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

REM ============================================================
REM  STEP 1: Check Python
REM ============================================================
echo [1/7] Checking Python installation...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Python is not installed!
    echo.
    echo Please install Python 3.10+ from: https://python.org/downloads
    echo.
    echo IMPORTANT: During installation, check "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%a in ('python --version') do set PYVER=%%a
echo       Python %PYVER% found!

REM ============================================================
REM  STEP 2: Create Virtual Environment
REM ============================================================
echo.
echo [2/7] Creating virtual environment...
if exist "venv" (
    echo       Removing old virtual environment...
    rmdir /s /q venv
)
python -m venv venv
if %errorLevel% neq 0 (
    echo [ERROR] Failed to create virtual environment!
    pause
    exit /b 1
)
echo       Virtual environment created!

REM ============================================================
REM  STEP 3: Install Dependencies
REM ============================================================
echo.
echo [3/7] Installing Python dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install dependencies!
    pause
    exit /b 1
)
echo       Dependencies installed!

REM ============================================================
REM  STEP 4: Create .env file
REM ============================================================
echo.
echo [4/7] Setting up environment...
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env
        echo       Created .env from example
    ) else (
        echo SECRET_KEY=your-secret-key-change-this-in-production> .env
        echo DATABASE_URL=sqlite:///./data/inventory.db>> .env
        echo       Created default .env file
    )
) else (
    echo       .env file already exists
)

REM ============================================================
REM  STEP 5: Create data directory and initialize database
REM ============================================================
echo.
echo [5/7] Initializing database...
if not exist "data" mkdir data
python -c "from app.database import engine, Base; from app import models; Base.metadata.create_all(bind=engine); print('       Database initialized!')"
if %errorLevel% neq 0 (
    echo [WARNING] Database initialization had issues. Will retry on first run.
)

REM ============================================================
REM  STEP 6: Download NSSM for service management
REM ============================================================
echo.
echo [6/7] Downloading service manager (NSSM)...
set "NSSM_DIR=%APP_DIR%tools\nssm"
if not exist "%NSSM_DIR%" mkdir "%NSSM_DIR%"
if not exist "%NSSM_DIR%\nssm.exe" (
    echo       Downloading NSSM...
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile '%NSSM_DIR%\nssm.zip'" 2>nul
    if exist "%NSSM_DIR%\nssm.zip" (
        powershell -Command "Expand-Archive -Path '%NSSM_DIR%\nssm.zip' -DestinationPath '%NSSM_DIR%' -Force"
        move "%NSSM_DIR%\nssm-2.24\win64\nssm.exe" "%NSSM_DIR%\nssm.exe" >nul 2>&1
        rmdir /s /q "%NSSM_DIR%\nssm-2.24" 2>nul
        del "%NSSM_DIR%\nssm.zip" 2>nul
        echo       NSSM downloaded!
    ) else (
        echo       [WARNING] Could not download NSSM. Service install may fail.
    )
) else (
    echo       NSSM already exists
)

REM ============================================================
REM  STEP 7: Create logs directory
REM ============================================================
echo.
echo [7/7] Creating logs directory...
if not exist "logs" mkdir logs
echo       Logs directory ready!

REM ============================================================
REM  SETUP COMPLETE
REM ============================================================
echo.
echo ============================================================
echo  SETUP COMPLETE!
echo ============================================================
echo.
echo  Your Inventory System is ready to use!
echo.
echo  NEXT STEPS:
echo  -----------------------------------------------------------
echo.
echo  1. TEST THE APP (manual start):
echo     Double-click: deploy\start.bat
echo     Then open: http://localhost:8000
echo.
echo  2. INSTALL AS SERVICE (auto-start on boot):
echo     Right-click deploy\install-service.bat
echo     Select "Run as administrator"
echo.
echo  3. FOR EXTERNAL ACCESS (Cloudflare Tunnel):
echo     Run: deploy\setup-cloudflare.bat
echo.
echo  4. TO BUILD EXECUTABLE (optional):
echo     Run: build-executable.bat
echo.
echo ============================================================
pause
