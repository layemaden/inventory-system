@echo off
echo ============================================
echo   INVENTORY SYSTEM - NETWORK SETUP
echo ============================================
echo.
echo This will allow other computers to connect
echo to this inventory system over the network.
echo.
echo You need to run this ONCE on the server computer.
echo.
pause

echo.
echo Adding Windows Firewall rule...
netsh advfirewall firewall add rule name="Inventory System" dir=in action=allow protocol=tcp localport=8000

echo.
echo ============================================
echo   SETUP COMPLETE!
echo ============================================
echo.
echo Firewall rule added successfully.
echo.
echo NEXT STEPS:
echo 1. Run InventorySystem.exe on this computer
echo 2. Note the "Other computers" URL shown
echo 3. On other computers, open a browser and go to that URL
echo.
pause
