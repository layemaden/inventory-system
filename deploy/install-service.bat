@echo off
REM ============================================================
REM  INVENTORY SYSTEM - INSTALL AS WINDOWS SERVICE
REM  Run this script as Administrator
REM ============================================================
setlocal

echo.
echo ============================================================
echo     INVENTORY SYSTEM - SERVICE INSTALLATION
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

set "APP_DIR=%~dp0.."
set "NSSM=%APP_DIR%\tools\nssm\nssm.exe"
set "SERVICE_NAME=InventorySystem"
set "PYTHON_EXE=%APP_DIR%\venv\Scripts\python.exe"

REM Check if NSSM exists
if not exist "%NSSM%" (
    echo [ERROR] NSSM not found. Please run install.bat first!
    pause
    exit /b 1
)

REM Stop existing service if running
echo [1/4] Stopping existing service (if any)...
"%NSSM%" stop %SERVICE_NAME% >nul 2>&1
"%NSSM%" remove %SERVICE_NAME% confirm >nul 2>&1
timeout /t 2 >nul

REM Install the service
echo [2/4] Installing service...
"%NSSM%" install %SERVICE_NAME% "%PYTHON_EXE%"
"%NSSM%" set %SERVICE_NAME% AppParameters "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"
"%NSSM%" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"%NSSM%" set %SERVICE_NAME% DisplayName "Inventory Management System"
"%NSSM%" set %SERVICE_NAME% Description "Local inventory and sales management system"
"%NSSM%" set %SERVICE_NAME% Start SERVICE_AUTO_START
"%NSSM%" set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\service.log"
"%NSSM%" set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\service-error.log"
"%NSSM%" set %SERVICE_NAME% AppRotateFiles 1
"%NSSM%" set %SERVICE_NAME% AppRotateBytes 1048576

REM Create logs directory
if not exist "%APP_DIR%\logs" mkdir "%APP_DIR%\logs"

echo [3/4] Starting service...
"%NSSM%" start %SERVICE_NAME%

echo [4/4] Verifying service status...
timeout /t 3 >nul
sc query %SERVICE_NAME% | findstr "RUNNING" >nul
if %errorLevel% equ 0 (
    echo.
    echo ============================================================
    echo  SUCCESS! Service installed and running!
    echo ============================================================
    echo.
    echo  Service Name:  %SERVICE_NAME%
    echo  Status:        RUNNING
    echo  Startup:       Automatic (starts on boot)
    echo.
    echo  Your app is now accessible at:
    echo  http://localhost:8000
    echo.
    echo  To manage the service:
    echo  - Stop:    net stop %SERVICE_NAME%
    echo  - Start:   net start %SERVICE_NAME%
    echo  - Remove:  deploy\uninstall-service.bat
    echo ============================================================
) else (
    echo.
    echo [WARNING] Service may not have started correctly.
    echo           Check logs at: %APP_DIR%\logs\
    echo.
)

pause
