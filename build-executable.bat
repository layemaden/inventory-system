@echo off
REM ============================================================
REM  INVENTORY SYSTEM - BUILD STANDALONE EXECUTABLE
REM  Creates a portable .exe that runs without Python installed
REM ============================================================
setlocal

echo.
echo ============================================================
echo     INVENTORY SYSTEM - BUILD EXECUTABLE
echo ============================================================
echo.

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

REM Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo         Please run setup-new-device.bat first.
    pause
    exit /b 1
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install PyInstaller if needed
echo [1/4] Checking PyInstaller...
pip show pyinstaller >nul 2>&1
if %errorLevel% neq 0 (
    echo       Installing PyInstaller...
    pip install pyinstaller
)
echo       PyInstaller ready!

REM Clean previous builds
echo.
echo [2/4] Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
echo       Cleaned!

REM Ensure openpyxl and et_xmlfile are installed
echo.
echo [3/5] Checking dependencies...
pip install openpyxl et_xmlfile --quiet

REM Build executable using spec file
echo.
echo [4/5] Building executable (this may take a few minutes)...
pyinstaller --noconfirm InventorySystem.spec

if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

REM Copy necessary files to dist
echo.
echo [5/5] Copying additional files...
if not exist "dist\InventorySystem\data" mkdir "dist\InventorySystem\data"
copy ".env.example" "dist\InventorySystem\.env" >nul 2>&1
echo       Files copied!

echo.
echo ============================================================
echo  BUILD COMPLETE!
echo ============================================================
echo.
echo  Your executable is at: dist\InventorySystem\
echo.
echo  To run: dist\InventorySystem\InventorySystem.exe
echo.
echo  You can copy the entire "dist\InventorySystem" folder
echo  to any Windows computer - no Python needed!
echo.
echo ============================================================
pause
