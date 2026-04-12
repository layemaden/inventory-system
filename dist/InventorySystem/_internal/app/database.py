from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# Get database URL (this properly evaluates the property)
database_url = settings.DATABASE_URL
print(f"[Database] Using: {database_url}")

engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False} if "sqlite" in database_url else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
