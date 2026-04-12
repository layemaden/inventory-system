import bcrypt
from itsdangerous import URLSafeTimedSerializer
from fastapi import Request, HTTPException, Depends
from functools import wraps
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from . import models

serializer = URLSafeTimedSerializer(settings.SECRET_KEY)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    return bcrypt.checkpw(plain_pin.encode('utf-8'), hashed_pin.encode('utf-8'))


def create_session_token(user_id: int, role: str) -> str:
    return serializer.dumps({"user_id": user_id, "role": role})


def verify_session_token(token: str, max_age: int = 86400) -> dict:
    try:
        data = serializer.loads(token, max_age=max_age)
        return data
    except Exception:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token:
        return None

    data = verify_session_token(token)
    if not data:
        return None

    user = db.query(models.User).filter(models.User.id == data["user_id"]).first()
    return user


def require_login(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
