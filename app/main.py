from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date

from .database import engine, get_db, Base
from .config import settings
from . import models, auth
from .routers import auth as auth_router, products, sales, reports, stock

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(auth_router.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(reports.router)
app.include_router(stock.router)


def init_db(db: Session):
    """Initialize database with default data if empty"""
    # Check if admin exists
    admin = db.query(models.User).filter(models.User.role == "admin").first()
    if not admin:
        # Create default admin
        admin = models.User(
            username="admin",
            password=auth.hash_password("admin123"),
            role="admin"
        )
        db.add(admin)

        # Create default staff
        staff = models.User(
            username="staff",
            pin=auth.hash_pin("1234"),
            role="staff"
        )
        db.add(staff)

        # Create default categories
        frozen = models.Category(name="Frozen Foods", description="Frozen food items")
        drinks = models.Category(name="Soft Drinks", description="Beverages and soft drinks")
        db.add(frozen)
        db.add(drinks)
        db.flush()

        # Create sample products (store_quantity = warehouse, shop_quantity = on shelf for sale)
        sample_products = [
            models.Product(name="Ice Cream Vanilla 1L", category_id=frozen.id, cost_price=150, selling_price=250, store_quantity=10, shop_quantity=10, reorder_level=5, unit="pack"),
            models.Product(name="Frozen Chicken 1kg", category_id=frozen.id, cost_price=800, selling_price=1200, store_quantity=10, shop_quantity=5, reorder_level=5, unit="pack"),
            models.Product(name="Frozen Fish Fillet 500g", category_id=frozen.id, cost_price=500, selling_price=750, store_quantity=5, shop_quantity=5, reorder_level=5, unit="pack"),
            models.Product(name="Coca-Cola 50cl", category_id=drinks.id, cost_price=100, selling_price=150, store_quantity=30, shop_quantity=20, reorder_level=20, unit="bottle"),
            models.Product(name="Fanta Orange 50cl", category_id=drinks.id, cost_price=100, selling_price=150, store_quantity=25, shop_quantity=20, reorder_level=20, unit="bottle"),
            models.Product(name="Sprite 50cl", category_id=drinks.id, cost_price=100, selling_price=150, store_quantity=20, shop_quantity=20, reorder_level=20, unit="bottle"),
            models.Product(name="Water 75cl", category_id=drinks.id, cost_price=50, selling_price=100, store_quantity=50, shop_quantity=50, reorder_level=30, unit="bottle"),
        ]
        for product in sample_products:
            db.add(product)

        db.commit()
        print("Database initialized with default data")


@app.on_event("startup")
async def startup_event():
    db = next(get_db())
    init_db(db)


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db)
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    # Today's stats
    today = date.today()

    today_sales = db.query(
        func.count(models.Sale.id).label("count"),
        func.sum(models.Sale.total_amount).label("total")
    ).filter(
        func.date(models.Sale.created_at) == today
    ).first()

    today_items = db.query(
        func.sum(models.SaleItem.quantity)
    ).join(models.Sale).filter(
        func.date(models.Sale.created_at) == today
    ).scalar() or 0

    # Low stock alerts (total stock = store + shop)
    low_stock = db.query(models.Product).join(models.Category).filter(
        (models.Product.store_quantity + models.Product.shop_quantity) <= models.Product.reorder_level
    ).order_by((models.Product.store_quantity + models.Product.shop_quantity).asc()).limit(5).all()

    # Recent sales
    recent_sales = db.query(models.Sale).order_by(
        models.Sale.created_at.desc()
    ).limit(5).all()

    # Today's profit (admin only)
    today_profit = None
    if user.role == "admin":
        profit_data = db.query(
            func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue"),
            func.sum(models.SaleItem.cost_price * models.SaleItem.quantity).label("cost")
        ).join(models.Sale).filter(
            func.date(models.Sale.created_at) == today
        ).first()

        if profit_data.revenue:
            today_profit = (profit_data.revenue or 0) - (profit_data.cost or 0)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "is_admin": user.role == "admin",
            "today_sales_count": today_sales.count or 0,
            "today_sales_total": today_sales.total or 0,
            "today_items_sold": today_items,
            "today_profit": today_profit,
            "low_stock": low_stock,
            "recent_sales": recent_sales
        }
    )


# Users management (admin only)
@app.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    users = db.query(models.User).order_by(models.User.username).all()
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "users": users, "user": user}
    )


@app.post("/users/add")
async def add_user(
    request: Request,
    username: str = None,
    pin: str = None,
    password: str = None,
    role: str = "staff",
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    form = await request.form()
    username = form.get("username")
    pin = form.get("pin")
    password = form.get("password")
    role = form.get("role", "staff")

    new_user = models.User(
        username=username,
        pin=auth.hash_pin(pin) if pin else None,
        password=auth.hash_password(password) if password else None,
        role=role
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/users", status_code=302)


@app.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin)
):
    if user_id == current_user.id:
        raise Exception("Cannot delete yourself")

    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if target_user:
        db.delete(target_user)
        db.commit()
    return RedirectResponse(url="/users", status_code=302)
