import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import date

from .database import engine, get_db, Base
from .config import settings
from . import models, auth
from .routers import auth as auth_router, products, sales, reports, stock, pos_banking

# Create tables
Base.metadata.create_all(bind=engine)

# Run migrations for new columns (SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS)
def run_migrations():
    """Add new columns to existing tables if they don't exist"""
    with engine.connect() as conn:
        # Check and add columns to products table
        result = conn.execute(text("PRAGMA table_info(products)"))
        columns = [row[1] for row in result.fetchall()]

        if 'pack_size' not in columns:
            conn.execute(text("ALTER TABLE products ADD COLUMN pack_size INTEGER DEFAULT 1"))
            print("Added pack_size column to products")
        if 'pack_price' not in columns:
            conn.execute(text("ALTER TABLE products ADD COLUMN pack_price FLOAT"))
            print("Added pack_price column to products")

        # Check and add columns to sale_items table
        result = conn.execute(text("PRAGMA table_info(sale_items)"))
        columns = [row[1] for row in result.fetchall()]

        if 'sale_type' not in columns:
            conn.execute(text("ALTER TABLE sale_items ADD COLUMN sale_type VARCHAR(10) DEFAULT 'unit'"))
            print("Added sale_type column to sale_items")
        if 'units_deducted' not in columns:
            conn.execute(text("ALTER TABLE sale_items ADD COLUMN units_deducted FLOAT DEFAULT 0"))
            # Set units_deducted to quantity for existing records
            conn.execute(text("UPDATE sale_items SET units_deducted = quantity WHERE units_deducted = 0 OR units_deducted IS NULL"))
            print("Added units_deducted column to sale_items")

        # Check and add columns to sales table
        result = conn.execute(text("PRAGMA table_info(sales)"))
        columns = [row[1] for row in result.fetchall()]

        if 'payment_method' not in columns:
            conn.execute(text("ALTER TABLE sales ADD COLUMN payment_method VARCHAR(10) DEFAULT 'cash'"))
            print("Added payment_method column to sales")

        # Create daily_carryover table if it doesn't exist
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_carryover (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date VARCHAR(10) UNIQUE NOT NULL,
                cash_carryover FLOAT DEFAULT 0,
                pos_carryover FLOAT DEFAULT 0,
                notes TEXT,
                updated_by INTEGER,
                updated_at DATETIME,
                FOREIGN KEY (updated_by) REFERENCES users(id)
            )
        """))

        # Create POS charge config table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pos_charge_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_type VARCHAR(20) NOT NULL,
                min_amount FLOAT NOT NULL,
                max_amount FLOAT NOT NULL,
                charge_type VARCHAR(20) DEFAULT 'fixed',
                charge_value FLOAT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Create POS transactions table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pos_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                transaction_type VARCHAR(20) NOT NULL,
                amount FLOAT NOT NULL,
                charge FLOAT DEFAULT 0,
                total FLOAT NOT NULL,
                customer_name VARCHAR(100),
                customer_phone VARCHAR(20),
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))

        conn.commit()

run_migrations()

app = FastAPI(title=settings.APP_NAME)

# Mount static files (create directory if it doesn't exist)
os.makedirs(settings.STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)

# Include routers
app.include_router(auth_router.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(reports.router)
app.include_router(stock.router)
app.include_router(pos_banking.router)


def init_db(db: Session):
    """Initialize database with default admin user only"""
    # Check if admin exists
    admin = db.query(models.User).filter(models.User.role == "admin").first()
    if not admin:
        # Create default admin only
        admin = models.User(
            username="admin",
            password=auth.hash_password("admin123"),
            role="admin"
        )
        db.add(admin)
        db.commit()
        print("Default admin user created (username: admin, password: admin123)")


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
            func.sum(models.SaleItem.cost_price).label("cost")  # cost_price is already total cost
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
