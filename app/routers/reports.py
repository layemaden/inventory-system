from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, date, timedelta
import csv
import io
from .. import models, auth
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


@router.get("", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    return templates.TemplateResponse(
        "reports/index.html",
        {"request": request, "user": user, "is_admin": user.role == "admin"}
    )


@router.get("/daily", response_class=HTMLResponse)
async def daily_sales_report(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    # Default to last 7 days
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=7)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Query daily sales with payment method breakdown
    daily_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.count(models.Sale.id).label("transaction_count"),
        func.sum(models.Sale.total_amount).label("total_sales"),
        func.sum(
            case((models.Sale.payment_method == 'cash', models.Sale.total_amount), else_=0)
        ).label("cash_total"),
        func.sum(
            case((models.Sale.payment_method == 'pos', models.Sale.total_amount), else_=0)
        ).label("pos_total"),
        func.count(
            case((models.Sale.payment_method == 'cash', 1), else_=None)
        ).label("cash_count"),
        func.count(
            case((models.Sale.payment_method == 'pos', 1), else_=None)
        ).label("pos_count")
    ).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        func.date(models.Sale.created_at)
    ).order_by(
        func.date(models.Sale.created_at).desc()
    ).all()

    # Get items sold per day
    items_by_date = {}
    items_query = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.sum(models.SaleItem.quantity).label("items_sold")
    ).join(models.SaleItem).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        func.date(models.Sale.created_at)
    ).all()

    for row in items_query:
        items_by_date[str(row.sale_date)] = row.items_sold

    # Get carryover data for date range
    carryovers = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date >= start_date,
        models.DailyCarryover.date <= end_date
    ).all()
    carryover_by_date = {c.date: c for c in carryovers}

    # Get POS banking data by date
    pos_banking_stats = db.query(
        func.date(models.POSTransaction.created_at).label("trans_date"),
        func.sum(models.POSTransaction.total).label("pos_banking_volume"),
        func.sum(models.POSTransaction.charge).label("pos_banking_profit"),
        func.count(models.POSTransaction.id).label("pos_banking_count")
    ).filter(
        func.date(models.POSTransaction.created_at) >= start,
        func.date(models.POSTransaction.created_at) <= end
    ).group_by(
        func.date(models.POSTransaction.created_at)
    ).all()

    pos_banking_by_date = {}
    for row in pos_banking_stats:
        pos_banking_by_date[str(row.trans_date)] = {
            "volume": row.pos_banking_volume or 0,
            "profit": row.pos_banking_profit or 0,
            "count": row.pos_banking_count or 0
        }

    report_data = []
    for row in daily_stats:
        date_str = str(row.sale_date)
        carryover = carryover_by_date.get(date_str)
        pos_banking = pos_banking_by_date.get(date_str, {"volume": 0, "profit": 0, "count": 0})
        report_data.append({
            "date": date_str,
            "transactions": row.transaction_count,
            "total_sales": row.total_sales or 0,
            "cash_total": row.cash_total or 0,
            "pos_total": row.pos_total or 0,
            "cash_count": row.cash_count or 0,
            "pos_count": row.pos_count or 0,
            "items_sold": items_by_date.get(date_str, 0),
            "cash_carryover": carryover.cash_carryover if carryover else 0,
            "pos_carryover": carryover.pos_carryover if carryover else 0,
            "notes": carryover.notes if carryover else "",
            "pos_banking_volume": pos_banking["volume"],
            "pos_banking_profit": pos_banking["profit"],
            "pos_banking_count": pos_banking["count"]
        })

    # Calculate totals
    total_transactions = sum(r["transactions"] for r in report_data)
    total_sales = sum(r["total_sales"] for r in report_data)
    total_items = sum(r["items_sold"] for r in report_data)
    total_cash = sum(r["cash_total"] for r in report_data)
    total_pos = sum(r["pos_total"] for r in report_data)
    total_pos_banking_volume = sum(r["pos_banking_volume"] for r in report_data)
    total_pos_banking_profit = sum(r["pos_banking_profit"] for r in report_data)

    return templates.TemplateResponse(
        "reports/daily.html",
        {
            "request": request,
            "user": user,
            "is_admin": user.role == "admin",
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
            "total_transactions": total_transactions,
            "total_sales": total_sales,
            "total_items": total_items,
            "total_cash": total_cash,
            "total_pos": total_pos,
            "total_pos_banking_volume": total_pos_banking_volume,
            "total_pos_banking_profit": total_pos_banking_profit
        }
    )


@router.get("/profit", response_class=HTMLResponse)
async def profit_report(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    # Default to last 7 days
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=7)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Query product sales profit by date
    profit_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue"),
        func.sum(models.SaleItem.cost_price).label("cost")  # cost_price is already total cost
    ).join(models.SaleItem).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        func.date(models.Sale.created_at)
    ).all()

    # Convert to dict for easy lookup
    sales_by_date = {}
    for row in profit_stats:
        sales_by_date[str(row.sale_date)] = {
            "revenue": row.revenue or 0,
            "cost": row.cost or 0
        }

    # Query POS banking profit by date (charge is the profit)
    pos_banking_stats = db.query(
        func.date(models.POSTransaction.created_at).label("trans_date"),
        func.sum(models.POSTransaction.total).label("pos_volume"),
        func.sum(models.POSTransaction.charge).label("pos_profit")
    ).filter(
        func.date(models.POSTransaction.created_at) >= start,
        func.date(models.POSTransaction.created_at) <= end
    ).group_by(
        func.date(models.POSTransaction.created_at)
    ).all()

    # Convert to dict for easy lookup
    pos_by_date = {}
    for row in pos_banking_stats:
        pos_by_date[str(row.trans_date)] = {
            "volume": row.pos_volume or 0,
            "profit": row.pos_profit or 0
        }

    # Get all unique dates
    all_dates = sorted(set(list(sales_by_date.keys()) + list(pos_by_date.keys())), reverse=True)

    report_data = []
    for date_str in all_dates:
        sales = sales_by_date.get(date_str, {"revenue": 0, "cost": 0})
        pos = pos_by_date.get(date_str, {"volume": 0, "profit": 0})

        revenue = sales["revenue"]
        cost = sales["cost"]
        sales_profit = revenue - cost
        pos_volume = pos["volume"]
        pos_profit = pos["profit"]
        total_profit = sales_profit + pos_profit
        margin = (sales_profit / revenue * 100) if revenue > 0 else 0

        report_data.append({
            "date": date_str,
            "revenue": revenue,
            "cost": cost,
            "sales_profit": sales_profit,
            "margin": round(margin, 1),
            "pos_volume": pos_volume,
            "pos_profit": pos_profit,
            "total_profit": total_profit
        })

    # Calculate totals
    total_revenue = sum(r["revenue"] for r in report_data)
    total_cost = sum(r["cost"] for r in report_data)
    total_sales_profit = total_revenue - total_cost
    total_pos_volume = sum(r["pos_volume"] for r in report_data)
    total_pos_profit = sum(r["pos_profit"] for r in report_data)
    total_profit = total_sales_profit + total_pos_profit
    total_margin = (total_sales_profit / total_revenue * 100) if total_revenue > 0 else 0

    return templates.TemplateResponse(
        "reports/profit.html",
        {
            "request": request,
            "user": user,
            "is_admin": True,
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "total_sales_profit": total_sales_profit,
            "total_pos_volume": total_pos_volume,
            "total_pos_profit": total_pos_profit,
            "total_profit": total_profit,
            "total_margin": round(total_margin, 1)
        }
    )


@router.get("/profit/by-product", response_class=HTMLResponse)
async def profit_by_product(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    profit_by_product = db.query(
        models.Product.name,
        models.Category.name.label("category"),
        func.sum(models.SaleItem.quantity).label("qty_sold"),
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue"),
        func.sum(models.SaleItem.cost_price).label("cost")  # cost_price is already total cost
    ).join(
        models.SaleItem, models.Product.id == models.SaleItem.product_id
    ).join(
        models.Sale, models.SaleItem.sale_id == models.Sale.id
    ).join(
        models.Category, models.Product.category_id == models.Category.id
    ).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        models.Product.id, models.Product.name, models.Category.name
    ).order_by(
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).desc()
    ).all()

    report_data = []
    for row in profit_by_product:
        revenue = row.revenue or 0
        cost = row.cost or 0
        profit = revenue - cost
        margin = (profit / revenue * 100) if revenue > 0 else 0

        report_data.append({
            "product": row.name,
            "category": row.category,
            "qty_sold": row.qty_sold,
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "margin": round(margin, 1)
        })

    return templates.TemplateResponse(
        "reports/profit_by_product.html",
        {
            "request": request,
            "user": user,
            "is_admin": True,
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date
        }
    )


@router.get("/export/daily")
async def export_daily_csv(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    daily_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.count(models.Sale.id).label("transaction_count"),
        func.sum(models.Sale.total_amount).label("total_sales")
    ).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        func.date(models.Sale.created_at)
    ).order_by(
        func.date(models.Sale.created_at).desc()
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Transactions", "Total Sales"])

    for row in daily_stats:
        writer.writerow([str(row.sale_date), row.transaction_count, row.total_sales or 0])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=daily_sales_{start_date}_to_{end_date}.csv"}
    )


@router.get("/carryover/{date_str}", response_class=JSONResponse)
async def get_carryover(
    date_str: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Get carryover data for a specific date"""
    carryover = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date == date_str
    ).first()

    if carryover:
        return {
            "date": carryover.date,
            "cash_carryover": carryover.cash_carryover or 0,
            "pos_carryover": carryover.pos_carryover or 0,
            "notes": carryover.notes or ""
        }
    return {
        "date": date_str,
        "cash_carryover": 0,
        "pos_carryover": 0,
        "notes": ""
    }


@router.post("/carryover/{date_str}", response_class=JSONResponse)
async def update_carryover(
    date_str: str,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Update carryover data for a specific date (admin only)"""
    body = await request.json()

    carryover = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date == date_str
    ).first()

    if carryover:
        carryover.cash_carryover = body.get("cash_carryover", 0)
        carryover.pos_carryover = body.get("pos_carryover", 0)
        carryover.notes = body.get("notes", "")
        carryover.updated_by = user.id
        carryover.updated_at = datetime.now()
    else:
        carryover = models.DailyCarryover(
            date=date_str,
            cash_carryover=body.get("cash_carryover", 0),
            pos_carryover=body.get("pos_carryover", 0),
            notes=body.get("notes", ""),
            updated_by=user.id,
            updated_at=datetime.now()
        )
        db.add(carryover)

    db.commit()

    return {"success": True, "message": "Carryover updated"}


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """System settings page"""
    # Get current settings
    pos_fee_percentage = get_setting(db, "pos_fee_percentage", "0")
    pos_fee_cap = get_setting(db, "pos_fee_cap", "100")

    return templates.TemplateResponse(
        "reports/settings.html",
        {
            "request": request,
            "user": user,
            "is_admin": True,
            "pos_fee_percentage": pos_fee_percentage,
            "pos_fee_cap": pos_fee_cap
        }
    )


@router.post("/settings", response_class=JSONResponse)
async def update_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Update system settings"""
    body = await request.json()

    for key, value in body.items():
        setting = db.query(models.SystemSettings).filter(
            models.SystemSettings.key == key
        ).first()

        if setting:
            setting.value = str(value)
        else:
            setting = models.SystemSettings(
                key=key,
                value=str(value)
            )
            db.add(setting)

    db.commit()

    return {"success": True, "message": "Settings updated"}


def get_setting(db: Session, key: str, default: str = "0") -> str:
    """Get a system setting value"""
    setting = db.query(models.SystemSettings).filter(
        models.SystemSettings.key == key
    ).first()
    return setting.value if setting else default


def calculate_pos_fee_per_transaction(amount: float, fee_percentage: float, fee_cap: float) -> float:
    """Calculate POS transaction fee for a single transaction (percentage-based, capped)"""
    if amount <= 0 or fee_percentage <= 0:
        return 0
    fee = amount * (fee_percentage / 100)
    return min(fee, fee_cap)


@router.get("/cash-pos-summary", response_class=HTMLResponse)
async def cash_pos_summary(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Comprehensive Cash & POS Summary Report"""
    # Default to last 7 days
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=7)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Get POS fee settings
    pos_fee_percentage = float(get_setting(db, "pos_fee_percentage", "0"))
    pos_fee_cap = float(get_setting(db, "pos_fee_cap", "100"))

    # Get individual POS sales to calculate fee per transaction
    pos_sales_list = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        models.Sale.total_amount
    ).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end,
        models.Sale.payment_method == 'pos'
    ).all()

    # Calculate fees per transaction and group by date
    pos_fees_by_date = {}
    for sale in pos_sales_list:
        date_str = str(sale.sale_date)
        fee = calculate_pos_fee_per_transaction(sale.total_amount, pos_fee_percentage, pos_fee_cap)
        pos_fees_by_date[date_str] = pos_fees_by_date.get(date_str, 0) + fee

    # Get sales by date and payment method
    sales_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.sum(case((models.Sale.payment_method == 'cash', models.Sale.total_amount), else_=0)).label("cash_sales"),
        func.sum(case((models.Sale.payment_method == 'pos', models.Sale.total_amount), else_=0)).label("pos_sales"),
        func.count(case((models.Sale.payment_method == 'cash', 1), else_=None)).label("cash_count"),
        func.count(case((models.Sale.payment_method == 'pos', 1), else_=None)).label("pos_count")
    ).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        func.date(models.Sale.created_at)
    ).all()

    sales_by_date = {}
    for row in sales_stats:
        sales_by_date[str(row.sale_date)] = {
            "cash_sales": row.cash_sales or 0,
            "pos_sales": row.pos_sales or 0,
            "cash_count": row.cash_count or 0,
            "pos_count": row.pos_count or 0
        }

    # Get POS banking by date
    # Need both total and amount for proper balance calculation
    pos_banking_stats = db.query(
        func.date(models.POSTransaction.created_at).label("trans_date"),
        # Withdrawal: total = full amount from customer's account, amount = cash given out
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.total), else_=0)).label("withdrawal_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.amount), else_=0)).label("withdrawal_amount"),
        # Deposit: total = cash received from customer, amount = transferred to customer's account
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.total), else_=0)).label("deposit_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.amount), else_=0)).label("deposit_amount"),
        func.sum(models.POSTransaction.charge).label("pos_banking_profit"),
        func.count(case((models.POSTransaction.transaction_type == 'withdrawal', 1), else_=None)).label("withdrawal_count"),
        func.count(case((models.POSTransaction.transaction_type == 'deposit', 1), else_=None)).label("deposit_count")
    ).filter(
        func.date(models.POSTransaction.created_at) >= start,
        func.date(models.POSTransaction.created_at) <= end
    ).group_by(
        func.date(models.POSTransaction.created_at)
    ).all()

    pos_banking_by_date = {}
    for row in pos_banking_stats:
        pos_banking_by_date[str(row.trans_date)] = {
            "withdrawal_total": row.withdrawal_total or 0,
            "withdrawal_amount": row.withdrawal_amount or 0,
            "deposit_total": row.deposit_total or 0,
            "deposit_amount": row.deposit_amount or 0,
            "pos_banking_profit": row.pos_banking_profit or 0,
            "withdrawal_count": row.withdrawal_count or 0,
            "deposit_count": row.deposit_count or 0
        }

    # Get carryover by date
    carryovers = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date >= start_date,
        models.DailyCarryover.date <= end_date
    ).all()
    carryover_by_date = {c.date: c for c in carryovers}

    # Get all unique dates
    all_dates = sorted(
        set(list(sales_by_date.keys()) + list(pos_banking_by_date.keys()) + list(carryover_by_date.keys()) + list(pos_fees_by_date.keys())),
        reverse=True
    )

    report_data = []
    for date_str in all_dates:
        sales = sales_by_date.get(date_str, {"cash_sales": 0, "pos_sales": 0, "cash_count": 0, "pos_count": 0})
        pos_banking = pos_banking_by_date.get(date_str, {
            "withdrawal_total": 0,
            "withdrawal_amount": 0,
            "deposit_total": 0,
            "deposit_amount": 0,
            "pos_banking_profit": 0,
            "withdrawal_count": 0,
            "deposit_count": 0
        })
        carryover = carryover_by_date.get(date_str)

        cash_carryover = carryover.cash_carryover if carryover else 0
        pos_carryover = carryover.pos_carryover if carryover else 0

        # Get POS sales fee for this date (calculated per transaction, already summed)
        pos_sales_fee = pos_fees_by_date.get(date_str, 0)

        # Calculate cash and POS balances for the day
        # Cash: Cash Sales + Deposit Total (cash received) - Withdrawal Amount (cash given out) + Carryover
        # POS: POS Sales - POS Fee + Withdrawal Total (received from customer) - Deposit Amount (transferred to customer) + Carryover
        cash_balance = (sales["cash_sales"] +
                       pos_banking["deposit_total"] -      # Cash received from customer
                       pos_banking["withdrawal_amount"] +  # Cash given to customer (amount, not total)
                       cash_carryover)
        pos_balance = (sales["pos_sales"] -
                      pos_sales_fee +                      # POS transaction fee deducted
                      pos_banking["withdrawal_total"] -    # Full amount from customer's account
                      pos_banking["deposit_amount"] +      # Amount transferred to customer's account
                      pos_carryover)

        report_data.append({
            "date": date_str,
            "cash_sales": sales["cash_sales"],
            "pos_sales": sales["pos_sales"],
            "pos_sales_fee": pos_sales_fee,
            "cash_count": sales["cash_count"],
            "pos_count": sales["pos_count"],
            "withdrawal_total": pos_banking["withdrawal_total"],
            "withdrawal_amount": pos_banking["withdrawal_amount"],
            "deposit_total": pos_banking["deposit_total"],
            "deposit_amount": pos_banking["deposit_amount"],
            "pos_banking_profit": pos_banking["pos_banking_profit"],
            "withdrawal_count": pos_banking["withdrawal_count"],
            "deposit_count": pos_banking["deposit_count"],
            "cash_carryover": cash_carryover,
            "pos_carryover": pos_carryover,
            "cash_balance": cash_balance,
            "pos_balance": pos_balance
        })

    # Calculate totals
    total_cash_sales = sum(r["cash_sales"] for r in report_data)
    total_pos_sales = sum(r["pos_sales"] for r in report_data)
    total_pos_sales_fee = sum(r["pos_sales_fee"] for r in report_data)
    total_sales = total_cash_sales + total_pos_sales
    total_withdrawal_total = sum(r["withdrawal_total"] for r in report_data)
    total_withdrawal_amount = sum(r["withdrawal_amount"] for r in report_data)
    total_deposit_total = sum(r["deposit_total"] for r in report_data)
    total_deposit_amount = sum(r["deposit_amount"] for r in report_data)
    total_pos_banking_profit = sum(r["pos_banking_profit"] for r in report_data)
    total_cash_carryover = sum(r["cash_carryover"] for r in report_data)
    total_pos_carryover = sum(r["pos_carryover"] for r in report_data)

    # Grand balances
    # Cash: Cash Sales + Deposit Total (cash received) - Withdrawal Amount (cash given) + Carryover
    grand_cash_balance = total_cash_sales + total_deposit_total - total_withdrawal_amount + total_cash_carryover
    # POS: POS Sales - POS Fee + Withdrawal Total (from customer) - Deposit Amount (to customer) + Carryover
    grand_pos_balance = total_pos_sales - total_pos_sales_fee + total_withdrawal_total - total_deposit_amount + total_pos_carryover

    return templates.TemplateResponse(
        "reports/cash_pos_summary.html",
        {
            "request": request,
            "user": user,
            "is_admin": True,
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
            "total_cash_sales": total_cash_sales,
            "total_pos_sales": total_pos_sales,
            "total_pos_sales_fee": total_pos_sales_fee,
            "total_sales": total_sales,
            "total_withdrawal_total": total_withdrawal_total,
            "total_withdrawal_amount": total_withdrawal_amount,
            "total_deposit_total": total_deposit_total,
            "total_deposit_amount": total_deposit_amount,
            "total_pos_banking_profit": total_pos_banking_profit,
            "total_cash_carryover": total_cash_carryover,
            "total_pos_carryover": total_pos_carryover,
            "grand_cash_balance": grand_cash_balance,
            "grand_pos_balance": grand_pos_balance,
            "pos_fee_percentage": pos_fee_percentage,
            "pos_fee_cap": pos_fee_cap
        }
    )
