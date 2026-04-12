import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    APP_NAME: str = "Inventory & Sales Tracker"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./inventory.db")

settings = Settings()
