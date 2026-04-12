from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .. import models, auth
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = auth.get_current_user(request, next(get_db()))
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login/pin")
async def login_with_pin(
    request: Request,
    pin: str = Form(...),
    db: Session = Depends(get_db)
):
    # Find user with matching PIN
    users = db.query(models.User).filter(models.User.pin.isnot(None)).all()

    for user in users:
        if auth.verify_pin(pin, user.pin):
            token = auth.create_session_token(user.id, user.role)
            response = RedirectResponse(url="/", status_code=302)
            response.set_cookie(
                key="session_token",
                value=token,
                httponly=True,
                max_age=86400,  # 24 hours
                samesite="lax"
            )
            return response

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid PIN"}
    )


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
            "login.html",
            {"request": request, "error": "Invalid credentials", "show_admin": True}
        )

    if not auth.verify_password(password, user.password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials", "show_admin": True}
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
