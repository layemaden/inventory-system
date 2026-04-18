import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, text, case
from datetime import date, timedelta

from .database import engine, get_db, Base
from .config import settings
from . import models, auth
from .routers import auth as auth_router, products, sales, reports, stock, pos_banking, balance

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

        if 'cash_amount' not in columns:
            conn.execute(text("ALTER TABLE sales ADD COLUMN cash_amount FLOAT DEFAULT 0"))
            print("Added cash_amount column to sales")

        if 'pos_amount' not in columns:
            conn.execute(text("ALTER TABLE sales ADD COLUMN pos_amount FLOAT DEFAULT 0"))
            print("Added pos_amount column to sales")

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

        # Create product_packs table for multiple pack categories
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS product_packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                pack_size INTEGER NOT NULL,
                pack_price FLOAT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """))

        # Add pack_id column to sale_items if it doesn't exist
        result = conn.execute(text("PRAGMA table_info(sale_items)"))
        columns = [row[1] for row in result.fetchall()]
        if 'pack_id' not in columns:
            conn.execute(text("ALTER TABLE sale_items ADD COLUMN pack_id INTEGER"))
            print("Added pack_id column to sale_items")

        # Create pending_carts table for hold/resume functionality
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_carts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                customer_note VARCHAR(200),
                total_amount FLOAT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """))

        # Create pending_cart_items table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_cart_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cart_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity FLOAT NOT NULL,
                unit_price FLOAT NOT NULL,
                sale_type VARCHAR(10) DEFAULT 'unit',
                pack_id INTEGER,
                pack_size INTEGER DEFAULT 1,
                FOREIGN KEY (cart_id) REFERENCES pending_carts(id),
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (pack_id) REFERENCES product_packs(id)
            )
        """))

        # Create balance_withdrawals table for tracking cash/POS withdrawals
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS balance_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                withdrawal_type VARCHAR(10) NOT NULL,
                amount FLOAT NOT NULL,
                reason TEXT,
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
import sys
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)

# Fix Jinja2 caching bug with PyInstaller
if getattr(sys, 'frozen', False):
    # Replace the LRU cache with a simple dict that won't cause unhashable errors
    class SimpleCache:
        def __init__(self):
            self._cache = {}
        def get(self, key, default=None):
            return self._cache.get(str(key), default)
        def __setitem__(self, key, value):
            self._cache[str(key)] = value
        def __getitem__(self, key):
            return self._cache[str(key)]
        def __contains__(self, key):
            return str(key) in self._cache
        def clear(self):
            self._cache.clear()
        def setdefault(self, key, default=None):
            return self._cache.setdefault(str(key), default)

    templates.env.cache = SimpleCache()
    templates.env.auto_reload = False

# Include routers
app.include_router(auth_router.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(reports.router)
app.include_router(stock.router)
app.include_router(pos_banking.router)
app.include_router(balance.router)


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
    today_cash_balance = None
    today_pos_balance = None

    if user.role == "admin":
        profit_data = db.query(
            func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue"),
            func.sum(models.SaleItem.cost_price).label("cost")  # cost_price is already total cost
        ).join(models.Sale).filter(
            func.date(models.Sale.created_at) == today
        ).first()

        if profit_data.revenue:
            today_profit = (profit_data.revenue or 0) - (profit_data.cost or 0)

        # Calculate today's cash and POS balance with carryover
        # Get yesterday's carryover (suggested = previous balance)
        yesterday = today - timedelta(days=1)
        yesterday_str = yesterday.isoformat()

        # Get yesterday's saved carryover or calculate suggested
        yesterday_carryover = db.query(models.DailyCarryover).filter(
            models.DailyCarryover.date == yesterday_str
        ).first()

        if yesterday_carryover:
            prev_cash_carryover = yesterday_carryover.cash_carryover or 0
            prev_pos_carryover = yesterday_carryover.pos_carryover or 0
        else:
            # No saved carryover, use 0 as starting point
            prev_cash_carryover = 0
            prev_pos_carryover = 0

        # Get today's sales by payment method
        today_sales_by_method = db.query(
            func.sum(case((models.Sale.payment_method == 'cash', models.Sale.total_amount), else_=0)).label("cash_sales"),
            func.sum(case((models.Sale.payment_method == 'pos', models.Sale.total_amount), else_=0)).label("pos_sales")
        ).filter(
            func.date(models.Sale.created_at) == today
        ).first()

        today_cash_sales = today_sales_by_method.cash_sales or 0 if today_sales_by_method else 0
        today_pos_sales = today_sales_by_method.pos_sales or 0 if today_sales_by_method else 0

        # Get today's POS banking transactions
        today_pos_banking = db.query(
            func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.total), else_=0)).label("withdrawal_total"),
            func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.amount), else_=0)).label("withdrawal_amount"),
            func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.total), else_=0)).label("deposit_total"),
            func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.amount), else_=0)).label("deposit_amount")
        ).filter(
            func.date(models.POSTransaction.created_at) == today
        ).first()

        withdrawal_total = today_pos_banking.withdrawal_total or 0 if today_pos_banking else 0
        withdrawal_amount = today_pos_banking.withdrawal_amount or 0 if today_pos_banking else 0
        deposit_total = today_pos_banking.deposit_total or 0 if today_pos_banking else 0
        deposit_amount = today_pos_banking.deposit_amount or 0 if today_pos_banking else 0

        # Calculate POS fee for today's POS sales
        pos_fee_setting = db.query(models.SystemSettings).filter(
            models.SystemSettings.key == "pos_fee_percentage"
        ).first()
        pos_fee_cap_setting = db.query(models.SystemSettings).filter(
            models.SystemSettings.key == "pos_fee_cap"
        ).first()
        pos_fee_percentage = float(pos_fee_setting.value) if pos_fee_setting else 0
        pos_fee_cap = float(pos_fee_cap_setting.value) if pos_fee_cap_setting else 100

        # Get individual POS sales to calculate fee per transaction
        today_pos_sales_list = db.query(models.Sale.total_amount).filter(
            func.date(models.Sale.created_at) == today,
            models.Sale.payment_method == 'pos'
        ).all()

        today_pos_fee = sum(
            min(sale.total_amount * (pos_fee_percentage / 100), pos_fee_cap)
            for sale in today_pos_sales_list
        ) if pos_fee_percentage > 0 else 0

        # Get today's balance withdrawals
        today_balance_withdrawals = db.query(
            func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'cash', models.BalanceWithdrawal.amount), else_=0)).label("cash_withdrawals"),
            func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'pos', models.BalanceWithdrawal.amount), else_=0)).label("pos_withdrawals")
        ).filter(
            func.date(models.BalanceWithdrawal.created_at) == today
        ).first()

        cash_balance_withdrawals = today_balance_withdrawals.cash_withdrawals or 0 if today_balance_withdrawals else 0
        pos_balance_withdrawals = today_balance_withdrawals.pos_withdrawals or 0 if today_balance_withdrawals else 0

        # Calculate balances
        # Cash: Carryover + Cash Sales + Deposits (cash in) - Withdrawals (cash out) - Balance Withdrawals
        today_cash_balance = prev_cash_carryover + today_cash_sales + deposit_total - withdrawal_amount - cash_balance_withdrawals

        # POS: Carryover + POS Sales - POS Fee + Withdrawals (POS in) - Deposits (POS out) - Balance Withdrawals
        today_pos_balance = prev_pos_carryover + today_pos_sales - today_pos_fee + withdrawal_total - deposit_amount - pos_balance_withdrawals

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "is_admin": user.role == "admin",
            "today_sales_count": today_sales.count or 0,
            "today_sales_total": today_sales.total or 0,
            "today_items_sold": today_items,
            "today_profit": today_profit,
            "today_cash_balance": today_cash_balance,
            "today_pos_balance": today_pos_balance,
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
        request,
        "users.html",
        {"users": users, "user": user}
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
