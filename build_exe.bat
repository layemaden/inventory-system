@echo off
echo ================================================
echo   Building Inventory System Executable
echo ================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Create/activate virtual environment
if not exist "venv_build" (
    echo Creating virtual environment...
    python -m venv venv_build
)

echo Activating virtual environment...
call venv_build\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

REM Build the executable
echo.
echo Building executable... (this may take a few minutes)
echo.

pyinstaller --noconfirm --onedir --console ^
    --name "InventorySystem" ^
    --add-data "app;app" ^
    --add-data "static;static" ^
    --add-data ".env.example;." ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.http.h11_impl" ^
    --hidden-import "uvicorn.protocols.http.httptools_impl" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.protocols.websockets.websockets_impl" ^
    --hidden-import "uvicorn.protocols.websockets.wsproto_impl" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "uvicorn.lifespan.off" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.loops.asyncio" ^
    --hidden-import "uvicorn.loops.uvloop" ^
    --hidden-import "sqlalchemy.dialects.sqlite" ^
    --hidden-import "aiosqlite" ^
    --hidden-import "bcrypt" ^
    --hidden-import "multipart" ^
    --hidden-import "jinja2" ^
    --hidden-import "dotenv" ^
    --collect-all "uvicorn" ^
    --collect-all "fastapi" ^
    --collect-all "starlette" ^
    run_server.py

if errorlevel 1 (
    echo.
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Build Complete!
echo ================================================
echo.
echo Executable created in: dist\InventorySystem\
echo.
echo To distribute:
echo   1. Copy the entire "dist\InventorySystem" folder
echo   2. Run "InventorySystem.exe" to start
echo.
pause
