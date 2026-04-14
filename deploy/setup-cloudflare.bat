@echo off
REM ============================================================
REM  INVENTORY SYSTEM - CLOUDFLARE TUNNEL SETUP
REM  Creates and configures Cloudflare Tunnel for external access
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo     CLOUDFLARE TUNNEL SETUP
echo ============================================================
echo.

set "APP_DIR=%~dp0.."
set "CF_DIR=%APP_DIR%\tools\cloudflare"

REM Step 1: Check if cloudflared is installed
echo [1/5] Checking for cloudflared...
where cloudflared >nul 2>&1
if %errorLevel% equ 0 (
    echo       cloudflared found in PATH!
    set "CLOUDFLARED=cloudflared"
    goto :check_login
)

if exist "%CF_DIR%\cloudflared.exe" (
    echo       cloudflared found in tools folder!
    set "CLOUDFLARED=%CF_DIR%\cloudflared.exe"
    goto :check_login
)

echo       cloudflared not found. Downloading...
if not exist "%CF_DIR%" mkdir "%CF_DIR%"

REM Download cloudflared
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF_DIR%\cloudflared.exe'"
if not exist "%CF_DIR%\cloudflared.exe" (
    echo [ERROR] Failed to download cloudflared!
    echo         Please download manually from:
    echo         https://github.com/cloudflare/cloudflared/releases
    pause
    exit /b 1
)
set "CLOUDFLARED=%CF_DIR%\cloudflared.exe"
echo       cloudflared downloaded!

:check_login
echo.
echo [2/5] Checking Cloudflare authentication...
echo.
echo       You need to authenticate with Cloudflare.
echo       A browser window will open for you to login.
echo.
pause

"%CLOUDFLARED%" tunnel login
if %errorLevel% neq 0 (
    echo [ERROR] Authentication failed!
    pause
    exit /b 1
)
echo       Authentication successful!

:create_tunnel
echo.
echo [3/5] Creating tunnel...
echo.
set /p "TUNNEL_NAME=Enter a name for your tunnel (e.g., inventory-system): "
if "%TUNNEL_NAME%"=="" set "TUNNEL_NAME=inventory-system"

"%CLOUDFLARED%" tunnel create %TUNNEL_NAME%
if %errorLevel% neq 0 (
    echo [WARNING] Tunnel may already exist. Continuing...
)

REM Get tunnel ID
for /f "tokens=1" %%a in ('"%CLOUDFLARED%" tunnel list ^| findstr /i "%TUNNEL_NAME%"') do (
    set "TUNNEL_ID=%%a"
)

echo       Tunnel created: %TUNNEL_NAME%
echo       Tunnel ID: %TUNNEL_ID%

:configure_dns
echo.
echo [4/5] Configuring DNS route...
echo.
echo       Your tunnel needs a domain/subdomain to route to.
echo       Example: inventory.yourdomain.com
echo.
set /p "HOSTNAME=Enter your hostname (e.g., inventory.yourdomain.com): "

"%CLOUDFLARED%" tunnel route dns %TUNNEL_NAME% %HOSTNAME%
if %errorLevel% neq 0 (
    echo [WARNING] DNS route may already exist or there was an error.
    echo           You may need to configure this manually in Cloudflare dashboard.
)

:create_config
echo.
echo [5/5] Creating tunnel configuration...

REM Create config file
echo tunnel: %TUNNEL_ID%> "%CF_DIR%\config.yml"
echo credentials-file: %USERPROFILE%\.cloudflared\%TUNNEL_ID%.json>> "%CF_DIR%\config.yml"
echo.>> "%CF_DIR%\config.yml"
echo ingress:>> "%CF_DIR%\config.yml"
echo   - hostname: %HOSTNAME%>> "%CF_DIR%\config.yml"
echo     service: http://localhost:8000>> "%CF_DIR%\config.yml"
echo   - service: http_status:404>> "%CF_DIR%\config.yml"

echo       Configuration saved to: %CF_DIR%\config.yml

REM Create tunnel start script
echo @echo off> "%APP_DIR%\deploy\start-tunnel.bat"
echo REM Start Cloudflare Tunnel>> "%APP_DIR%\deploy\start-tunnel.bat"
echo echo Starting Cloudflare Tunnel...>> "%APP_DIR%\deploy\start-tunnel.bat"
echo echo Your app will be accessible at: https://%HOSTNAME%>> "%APP_DIR%\deploy\start-tunnel.bat"
echo echo.>> "%APP_DIR%\deploy\start-tunnel.bat"
echo "%CLOUDFLARED%" tunnel --config "%CF_DIR%\config.yml" run %TUNNEL_NAME%>> "%APP_DIR%\deploy\start-tunnel.bat"
echo pause>> "%APP_DIR%\deploy\start-tunnel.bat"

echo.
echo ============================================================
echo  SETUP COMPLETE!
echo ============================================================
echo.
echo  Your Cloudflare Tunnel is configured!
echo.
echo  Tunnel Name:  %TUNNEL_NAME%
echo  Domain:       https://%HOSTNAME%
echo.
echo  TO START THE TUNNEL:
echo  1. Make sure your app is running (deploy\start.bat or the service)
echo  2. Run: deploy\start-tunnel.bat
echo.
echo  TO INSTALL TUNNEL AS SERVICE (auto-start):
echo  Run this command as Administrator:
echo  "%CLOUDFLARED%" service install
echo.
echo  Your app will then be accessible at:
echo  https://%HOSTNAME%
echo.
echo ============================================================
pause
