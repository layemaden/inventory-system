from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .. import models, auth
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = auth.get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {})


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    user = auth.get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "signup.html", {})


@router.post("/signup")
async def signup_staff(
    request: Request,
    username: str = Form(...),
    pin: str = Form(...),
    confirm_pin: str = Form(...),
    db: Session = Depends(get_db)
):
    # Validate PIN
    if len(pin) < 4 or len(pin) > 6:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "PIN must be 4-6 digits"}
        )

    if not pin.isdigit():
        return templates.TemplateResponse(
            request, "signup.html", {"error": "PIN must contain only numbers"}
        )

    if pin != confirm_pin:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "PINs do not match"}
        )

    # Check if username already exists
    existing_user = db.query(models.User).filter(models.User.username == username).first()
    if existing_user:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Username already taken"}
        )

    # Create new staff user
    new_user = models.User(
        username=username,
        pin=auth.hash_pin(pin),
        role="staff"
    )
    db.add(new_user)
    db.commit()

    # Auto-login after signup
    token = auth.create_session_token(new_user.id, new_user.role)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax"
    )
    return response


@router.post("/login/staff")
async def login_staff(
    request: Request,
    username: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.username == username).first()

    if not user or not user.pin:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid username or PIN", "show_staff": True}
        )

    if not auth.verify_pin(pin, user.pin):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid username or PIN", "show_staff": True}
        )

    token = auth.create_session_token(user.id, user.role)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax"
    )
    return response


@router.post("/login/password")
async def login_with_password(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.username == username).first()

    if not user or not user.password:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid credentials", "show_admin": True}
        )

    if not auth.verify_password(password, user.password):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid credentials", "show_admin": True}
        )

    token = auth.create_session_token(user.id, user.role)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax"
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("session_token")
    return response
