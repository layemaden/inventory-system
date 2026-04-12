import os
import sys
from dotenv import load_dotenv

load_dotenv()

def get_base_path():
    """Get the base path for bundled resources (templates, static files)."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        # For onefile: sys._MEIPASS is the temp extraction folder
        # For onedir: files are next to executable in _internal
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        return os.path.join(os.path.dirname(sys.executable), '_internal')
    else:
        # Running as script
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_data_path():
    """Get the path for persistent data (database, etc.) - survives rebuilds."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle - store data in user's AppData folder
        app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        data_dir = os.path.join(app_data, 'InventorySystem')
    else:
        # Running as script - store in project folder
        data_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Create directory if it doesn't exist
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

class Settings:
    APP_NAME: str = "Inventory & Sales Tracker"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")

    @property
    def DATABASE_URL(self):
        # Check for environment variable first
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url
        # Default: store database in persistent data folder
        db_path = os.path.join(get_data_path(), "inventory.db")
        return f"sqlite:///{db_path}"

    @property
    def TEMPLATES_DIR(self):
        return os.path.join(get_base_path(), "app", "templates")

    @property
    def STATIC_DIR(self):
        return os.path.join(get_base_path(), "app", "static")

settings = Settings()
