"""
Inventory System Launcher
Double-click to start the server, then open your browser to http://localhost:8000
"""
import os
import sys
import webbrowser
import threading
import time
import socket

# Set up paths for PyInstaller bundled app
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    BASE_DIR = os.path.dirname(sys.executable)
    # Add the _internal folder to path for PyInstaller onedir mode
    INTERNAL_DIR = os.path.join(BASE_DIR, '_internal')
    if os.path.exists(INTERNAL_DIR):
        sys.path.insert(0, INTERNAL_DIR)
    sys.path.insert(0, BASE_DIR)
    os.chdir(BASE_DIR)
    # Data is stored in AppData (survives rebuilds)
    DATA_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'InventorySystem')
else:
    # Running as script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    os.chdir(BASE_DIR)
    DATA_DIR = BASE_DIR

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Set DATABASE_URL environment variable BEFORE importing app
# This ensures the database is always in the persistent DATA_DIR
DB_PATH = os.path.join(DATA_DIR, "inventory.db")
os.environ['DATABASE_URL'] = f"sqlite:///{DB_PATH}"

def get_local_ip():
    """Get the local IP address for network access"""
    try:
        # Create a socket to determine the local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Unable to detect"


def open_browser():
    """Open browser after a short delay"""
    time.sleep(2)
    webbrowser.open("http://localhost:8000")

def main():
    local_ip = get_local_ip()

    print("=" * 58)
    print("           INVENTORY MANAGEMENT SYSTEM")
    print("=" * 58)
    print()
    print("  Starting server...")
    print("  The application will open in your browser automatically.")
    print()
    print("  ACCESS URLs:")
    print("  ------------")
    print(f"  This computer:      http://localhost:8000")
    print(f"  Other computers:    http://{local_ip}:8000")
    print()
    print("  Share the 'Other computers' URL with your staff!")
    print()
    print("-" * 58)
    print(f"  Database: {DB_PATH}")
    print(f"  Data folder: {DATA_DIR}")
    print("  (Your data is safe - rebuilding the app won't delete it)")
    print("-" * 58)
    print()
    print("  Press Ctrl+C to stop the server")
    print("=" * 58)

    # Start browser in background thread
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    # Import and run uvicorn
    import uvicorn
    from app.main import app

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )

if __name__ == "__main__":
    main()
