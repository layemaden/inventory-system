@echo off
REM ============================================================
REM  INVENTORY SYSTEM - QUICK BUILD
REM ============================================================
cd /d "%~dp0"

echo Building Inventory System executable...
echo.

REM Activate venv and build
call venv\Scripts\activate.bat
pip install pyinstaller openpyxl et_xmlfile --quiet

REM Clean old builds
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

REM Build
pyinstaller --noconfirm InventorySystem.spec

if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo BUILD SUCCESS!
    echo Executable: dist\InventorySystem\InventorySystem.exe
    echo ========================================
) else (
    echo.
    echo BUILD FAILED!
)

pause
