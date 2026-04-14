@echo off
REM ============================================================
REM  INVENTORY SYSTEM - START SERVER
REM  Run this to start the server manually
REM ============================================================
setlocal

set "APP_DIR=%~dp0.."
cd /d "%APP_DIR%"

echo.
echo ============================================================
echo     INVENTORY SYSTEM - STARTING SERVER
echo ============================================================
echo.

REM Get local IP address
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do set "LOCAL_IP=%%b"
)

echo  ACCESS URLs:
echo  ----------------------------------------------------
echo  This computer:     http://localhost:8000
echo  Local network:     http://%LOCAL_IP%:8000
echo  ----------------------------------------------------
echo.
echo  Press Ctrl+C to stop the server
echo.
echo ============================================================

REM Activate virtual environment and start server
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
