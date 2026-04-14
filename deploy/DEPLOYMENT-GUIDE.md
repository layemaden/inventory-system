# Inventory System - Deployment Guide

## Quick Start (Local Network Only)

### Option 1: Run Manually
```batch
deploy\install.bat     # First time setup
deploy\start.bat       # Start server
```
Access at: `http://localhost:8000` or `http://YOUR_IP:8000`

### Option 2: Run as Windows Service (Auto-start on boot)
```batch
deploy\install.bat           # First time setup
deploy\install-service.bat   # Install as service (run as Admin)
```

---

## Full Deployment Guide

### Prerequisites
- Windows 10/11
- Python 3.10 or higher
- Administrator access (for service installation)

### Step 1: Initial Installation

1. **Run the installer** (as Administrator):
   ```
   Right-click deploy\install.bat → Run as administrator
   ```

2. This will:
   - Check Python installation
   - Create virtual environment
   - Install dependencies
   - Initialize database
   - Download NSSM (service manager)

### Step 2: Test the Application

1. Run `deploy\start.bat`
2. Open browser: `http://localhost:8000`
3. Verify everything works
4. Press `Ctrl+C` to stop

### Step 3: Install as Windows Service

For the app to run automatically when Windows starts:

1. **Run as Administrator**:
   ```
   Right-click deploy\install-service.bat → Run as administrator
   ```

2. The service will:
   - Start automatically on boot
   - Run in background
   - Restart if it crashes

**Manage the service:**
```batch
net stop InventorySystem    # Stop
net start InventorySystem   # Start
deploy\uninstall-service.bat   # Remove completely
```

---

## External Access (Cloudflare Tunnel)

To access your app from outside your local network:

### Step 1: Setup Cloudflare Account

1. Go to [cloudflare.com](https://cloudflare.com) and create free account
2. Add your domain (or use a free subdomain)

### Step 2: Run Tunnel Setup

```batch
deploy\setup-cloudflare.bat
```

This will:
- Download cloudflared
- Authenticate with Cloudflare
- Create a tunnel
- Configure DNS routing
- Create start script

### Step 3: Start the Tunnel

1. Make sure your app is running (service or manual)
2. Run `deploy\start-tunnel.bat`
3. Access via: `https://yourdomain.com`

### Step 4: Install Tunnel as Service (Optional)

To auto-start the tunnel on boot:
```batch
cloudflared service install
```

---

## File Structure

```
inventory-system/
├── app/                    # Application code
├── data/                   # Database (created on first run)
├── logs/                   # Service logs
├── tools/
│   ├── nssm/              # Windows service manager
│   └── cloudflare/        # Cloudflared and config
├── venv/                   # Python virtual environment
├── deploy/
│   ├── install.bat        # Initial setup
│   ├── start.bat          # Manual start
│   ├── install-service.bat    # Install as service
│   ├── uninstall-service.bat  # Remove service
│   ├── setup-cloudflare.bat   # Cloudflare tunnel setup
│   └── start-tunnel.bat       # Start tunnel (created by setup)
└── requirements.txt
```

---

## Troubleshooting

### App won't start
1. Check Python is installed: `python --version`
2. Check logs: `logs\service.log` and `logs\service-error.log`
3. Run manually to see errors: `deploy\start.bat`

### Service won't install
1. Run as Administrator
2. Check if service exists: `sc query InventorySystem`
3. Remove old service: `deploy\uninstall-service.bat`

### Can't access from other devices on network
1. Check Windows Firewall - allow port 8000
2. Use your computer's IP address, not localhost
3. Find your IP: `ipconfig` (look for IPv4 Address)

### Cloudflare tunnel issues
1. Check tunnel status: `cloudflared tunnel list`
2. Check config: `tools\cloudflare\config.yml`
3. Test locally first before tunnel

---

## Backup & Restore

### Backup
Copy these folders:
- `data/` - Database
- `tools/cloudflare/` - Tunnel config (if using)

### Restore
1. Run `deploy\install.bat` on new machine
2. Copy backup folders to same locations
3. Run `deploy\install-service.bat`

---

## Support

For issues or questions:
- Check logs in `logs/` folder
- Review error messages in console
- Verify all prerequisites are met
