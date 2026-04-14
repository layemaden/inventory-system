@echo off
REM ============================================================
REM  INVENTORY SYSTEM - UNINSTALL WINDOWS SERVICE
REM  Run this script as Administrator
REM ============================================================
setlocal

echo.
echo ============================================================
echo     INVENTORY SYSTEM - SERVICE REMOVAL
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

REM Check if NSSM exists
if not exist "%NSSM%" (
    echo [WARNING] NSSM not found. Trying with sc command...
    sc stop %SERVICE_NAME% >nul 2>&1
    sc delete %SERVICE_NAME% >nul 2>&1
    goto :check_result
)

echo [1/3] Stopping service...
"%NSSM%" stop %SERVICE_NAME% >nul 2>&1
timeout /t 2 >nul

echo [2/3] Removing service...
"%NSSM%" remove %SERVICE_NAME% confirm >nul 2>&1

:check_result
echo [3/3] Verifying removal...
timeout /t 2 >nul
sc query %SERVICE_NAME% >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ============================================================
    echo  SUCCESS! Service has been removed.
    echo ============================================================
    echo.
    echo  The Inventory System service is no longer installed.
    echo  Your data and application files remain intact.
    echo.
    echo  To reinstall: deploy\install-service.bat
    echo  To start manually: deploy\start.bat
    echo ============================================================
) else (
    echo.
    echo [WARNING] Service may still exist.
    echo           Try restarting your computer.
)

pause
