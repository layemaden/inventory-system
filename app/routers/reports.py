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
    user: models.User = Depends(auth.require_admin)
):
    return templates.TemplateResponse(
        request, "reports/index.html", {"user": user, "is_admin": True}
    )


@router.get("/daily", response_class=HTMLResponse)
async def daily_sales_report(
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

    # Query daily sales with payment method breakdown
    # For split payments, use cash_amount/pos_amount; for single payments, use total_amount
    daily_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.count(models.Sale.id).label("transaction_count"),
        func.sum(models.Sale.total_amount).label("total_sales"),
        func.sum(
            case(
                (models.Sale.payment_method == 'cash', models.Sale.total_amount),
                (models.Sale.payment_method == 'split', models.Sale.cash_amount),
                else_=0
            )
        ).label("cash_total"),
        func.sum(
            case(
                (models.Sale.payment_method == 'pos', models.Sale.total_amount),
                (models.Sale.payment_method == 'split', models.Sale.pos_amount),
                else_=0
            )
        ).label("pos_total"),
        func.count(
            case((models.Sale.payment_method == 'cash', 1), else_=None)
        ).label("cash_count"),
        func.count(
            case((models.Sale.payment_method == 'pos', 1), else_=None)
        ).label("pos_count"),
        func.count(
            case((models.Sale.payment_method == 'split', 1), else_=None)
        ).label("split_count")
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
            "split_count": row.split_count or 0,
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
        request, "reports/daily.html", {"user": user,
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
        request, "reports/profit.html", {"user": user,
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
        request, "reports/profit_by_product.html", {"user": user,
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
    user: models.User = Depends(auth.require_admin)
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


def calculate_suggested_carryover(db: Session, date_str: str) -> dict:
    """
    Calculate suggested carryover for a given date based on previous day's data.

    Formula:
    - Cash: Previous cash_carryover + Previous cash_sales + Previous deposit_total - Previous withdrawal_amount
    - POS: Previous pos_carryover + Previous pos_sales - Previous pos_fee + Previous withdrawal_total - Previous deposit_amount
    """
    # Get the previous day
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    prev_date = target_date - timedelta(days=1)
    prev_date_str = prev_date.isoformat()

    # Get previous day's carryover
    prev_carryover = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date == prev_date_str
    ).first()

    prev_cash_carryover = prev_carryover.cash_carryover if prev_carryover else 0
    prev_pos_carryover = prev_carryover.pos_carryover if prev_carryover else 0

    # Get previous day's sales by payment method (including split payments)
    prev_sales = db.query(
        func.sum(case(
            (models.Sale.payment_method == 'cash', models.Sale.total_amount),
            (models.Sale.payment_method == 'split', models.Sale.cash_amount),
            else_=0
        )).label("cash_sales"),
        func.sum(case(
            (models.Sale.payment_method == 'pos', models.Sale.total_amount),
            (models.Sale.payment_method == 'split', models.Sale.pos_amount),
            else_=0
        )).label("pos_sales")
    ).filter(
        func.date(models.Sale.created_at) == prev_date
    ).first()

    prev_cash_sales = prev_sales.cash_sales or 0 if prev_sales else 0
    prev_pos_sales = prev_sales.pos_sales or 0 if prev_sales else 0

    # Get POS fee settings for calculating POS sales fee
    pos_fee_percentage = float(get_setting(db, "pos_fee_percentage", "0"))
    pos_fee_cap = float(get_setting(db, "pos_fee_cap", "100"))

    # Calculate POS sales fee per transaction for previous day (including split payments)
    prev_pos_sales_list = db.query(
        models.Sale.total_amount, models.Sale.payment_method, models.Sale.pos_amount
    ).filter(
        func.date(models.Sale.created_at) == prev_date,
        models.Sale.payment_method.in_(['pos', 'split'])
    ).all()

    prev_pos_fee = sum(
        calculate_pos_fee_per_transaction(
            sale.total_amount if sale.payment_method == 'pos' else sale.pos_amount,
            pos_fee_percentage,
            pos_fee_cap
        )
        for sale in prev_pos_sales_list
    )

    # Get previous day's POS banking transactions
    prev_pos_banking = db.query(
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.total), else_=0)).label("withdrawal_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.amount), else_=0)).label("withdrawal_amount"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.total), else_=0)).label("deposit_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.amount), else_=0)).label("deposit_amount")
    ).filter(
        func.date(models.POSTransaction.created_at) == prev_date
    ).first()

    withdrawal_total = prev_pos_banking.withdrawal_total or 0 if prev_pos_banking else 0
    withdrawal_amount = prev_pos_banking.withdrawal_amount or 0 if prev_pos_banking else 0
    deposit_total = prev_pos_banking.deposit_total or 0 if prev_pos_banking else 0
    deposit_amount = prev_pos_banking.deposit_amount or 0 if prev_pos_banking else 0

    # Get previous day's balance withdrawals
    prev_balance_withdrawals = db.query(
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'cash', models.BalanceWithdrawal.amount), else_=0)).label("cash_withdrawals"),
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'pos', models.BalanceWithdrawal.amount), else_=0)).label("pos_withdrawals")
    ).filter(
        func.date(models.BalanceWithdrawal.created_at) == prev_date
    ).first()

    cash_balance_withdrawals = prev_balance_withdrawals.cash_withdrawals or 0 if prev_balance_withdrawals else 0
    pos_balance_withdrawals = prev_balance_withdrawals.pos_withdrawals or 0 if prev_balance_withdrawals else 0

    # Calculate suggested carryover
    # Cash: Previous carryover + Cash sales + Deposit (cash received) - Withdrawal (cash given out) - Balance withdrawals
    suggested_cash = prev_cash_carryover + prev_cash_sales + deposit_total - withdrawal_amount - cash_balance_withdrawals

    # POS: Previous carryover + POS sales - POS fee + Withdrawal (from customer account) - Deposit (to customer account) - Balance withdrawals
    suggested_pos = prev_pos_carryover + prev_pos_sales - prev_pos_fee + withdrawal_total - deposit_amount - pos_balance_withdrawals

    return {
        "suggested_cash": suggested_cash,
        "suggested_pos": suggested_pos,
        "breakdown": {
            "prev_cash_carryover": prev_cash_carryover,
            "prev_pos_carryover": prev_pos_carryover,
            "prev_cash_sales": prev_cash_sales,
            "prev_pos_sales": prev_pos_sales,
            "prev_pos_fee": prev_pos_fee,
            "withdrawal_total": withdrawal_total,
            "withdrawal_amount": withdrawal_amount,
            "deposit_total": deposit_total,
            "deposit_amount": deposit_amount,
            "cash_balance_withdrawals": cash_balance_withdrawals,
            "pos_balance_withdrawals": pos_balance_withdrawals
        }
    }


@router.get("/carryover/{date_str}", response_class=JSONResponse)
async def get_carryover(
    date_str: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Get carryover data for a specific date with suggested values"""
    carryover = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date == date_str
    ).first()

    # Calculate suggested carryover from previous day
    suggested = calculate_suggested_carryover(db, date_str)

    if carryover:
        return {
            "date": carryover.date,
            "cash_carryover": carryover.cash_carryover or 0,
            "pos_carryover": carryover.pos_carryover or 0,
            "notes": carryover.notes or "",
            "suggested_cash": suggested["suggested_cash"],
            "suggested_pos": suggested["suggested_pos"],
            "breakdown": suggested["breakdown"]
        }
    return {
        "date": date_str,
        "cash_carryover": suggested["suggested_cash"],
        "pos_carryover": suggested["suggested_pos"],
        "notes": "",
        "suggested_cash": suggested["suggested_cash"],
        "suggested_pos": suggested["suggested_pos"],
        "breakdown": suggested["breakdown"]
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
        request, "reports/settings.html", {"user": user,
            "is_admin": True,
            "pos_fee_percentage": pos_fee_percentage,
            "pos_fee_cap": pos_fee_cap
        }
    )


@router.get("/today-summary", response_class=HTMLResponse)
async def today_summary(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Today's Cash & POS Summary Report"""
    today = date.today()
    today_str = today.isoformat()
    yesterday_str = (today - timedelta(days=1)).isoformat()

    # Get POS fee settings
    pos_fee_percentage = float(get_setting(db, "pos_fee_percentage", "0"))
    pos_fee_cap = float(get_setting(db, "pos_fee_cap", "100"))

    # Get today's sales (including split payments)
    sales_stats = db.query(
        func.sum(case(
            (models.Sale.payment_method == 'cash', models.Sale.total_amount),
            (models.Sale.payment_method == 'split', models.Sale.cash_amount),
            else_=0
        )).label("cash_sales"),
        func.sum(case(
            (models.Sale.payment_method == 'pos', models.Sale.total_amount),
            (models.Sale.payment_method == 'split', models.Sale.pos_amount),
            else_=0
        )).label("pos_sales"),
        func.count(case((models.Sale.payment_method == 'cash', 1), else_=None)).label("cash_count"),
        func.count(case((models.Sale.payment_method == 'pos', 1), else_=None)).label("pos_count"),
        func.count(case((models.Sale.payment_method == 'split', 1), else_=None)).label("split_count")
    ).filter(
        func.date(models.Sale.created_at) == today
    ).first()

    cash_sales = sales_stats.cash_sales or 0
    pos_sales = sales_stats.pos_sales or 0
    cash_count = sales_stats.cash_count or 0
    pos_count = sales_stats.pos_count or 0
    split_count = sales_stats.split_count or 0

    # Calculate POS fee per transaction (including POS portion of split payments)
    pos_sales_list = db.query(models.Sale.total_amount, models.Sale.payment_method, models.Sale.pos_amount).filter(
        func.date(models.Sale.created_at) == today,
        models.Sale.payment_method.in_(['pos', 'split'])
    ).all()
    pos_fee = sum(
        calculate_pos_fee_per_transaction(
            s.total_amount if s.payment_method == 'pos' else s.pos_amount,
            pos_fee_percentage,
            pos_fee_cap
        ) for s in pos_sales_list
    )

    # Get today's POS banking
    pos_banking_stats = db.query(
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.total), else_=0)).label("withdrawal_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.amount), else_=0)).label("withdrawal_amount"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.total), else_=0)).label("deposit_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.amount), else_=0)).label("deposit_amount"),
        func.sum(models.POSTransaction.charge).label("pos_banking_profit"),
        func.count(case((models.POSTransaction.transaction_type == 'withdrawal', 1), else_=None)).label("withdrawal_count"),
        func.count(case((models.POSTransaction.transaction_type == 'deposit', 1), else_=None)).label("deposit_count")
    ).filter(
        func.date(models.POSTransaction.created_at) == today
    ).first()

    withdrawal_total = pos_banking_stats.withdrawal_total or 0
    withdrawal_amount = pos_banking_stats.withdrawal_amount or 0
    deposit_total = pos_banking_stats.deposit_total or 0
    deposit_amount = pos_banking_stats.deposit_amount or 0
    pos_banking_profit = pos_banking_stats.pos_banking_profit or 0
    withdrawal_count = pos_banking_stats.withdrawal_count or 0
    deposit_count = pos_banking_stats.deposit_count or 0

    # Get yesterday's carryover
    yesterday_carryover = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date == yesterday_str
    ).first()

    prev_cash_carryover = yesterday_carryover.cash_carryover if yesterday_carryover else 0
    prev_pos_carryover = yesterday_carryover.pos_carryover if yesterday_carryover else 0

    # Get today's balance withdrawals
    balance_withdrawal_stats = db.query(
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'cash', models.BalanceWithdrawal.amount), else_=0)).label("cash_withdrawals"),
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'pos', models.BalanceWithdrawal.amount), else_=0)).label("pos_withdrawals"),
        func.count(case((models.BalanceWithdrawal.withdrawal_type == 'cash', 1), else_=None)).label("cash_withdrawal_count"),
        func.count(case((models.BalanceWithdrawal.withdrawal_type == 'pos', 1), else_=None)).label("pos_withdrawal_count")
    ).filter(
        func.date(models.BalanceWithdrawal.created_at) == today
    ).first()

    cash_balance_withdrawals = balance_withdrawal_stats.cash_withdrawals or 0
    pos_balance_withdrawals = balance_withdrawal_stats.pos_withdrawals or 0
    cash_withdrawal_count = balance_withdrawal_stats.cash_withdrawal_count or 0
    pos_withdrawal_count = balance_withdrawal_stats.pos_withdrawal_count or 0

    # Calculate balances
    # Cash: Cash Sales + Deposit Total (cash received) - Withdrawal Amount (cash given) + Previous Day's Cash Carryover - Balance Withdrawals
    cash_balance = cash_sales + deposit_total - withdrawal_amount + prev_cash_carryover - cash_balance_withdrawals
    # POS: POS Sales - POS Fee + Withdrawal Total (from customer) - Deposit Amount (to customer) + Previous Day's POS Carryover - Balance Withdrawals
    pos_balance = pos_sales - pos_fee + withdrawal_total - deposit_amount + prev_pos_carryover - pos_balance_withdrawals

    total_sales = cash_sales + pos_sales

    return templates.TemplateResponse(
        request, "reports/today_summary.html", {
            "user": user,
            "is_admin": True,
            "today": today_str,
            "cash_sales": cash_sales,
            "pos_sales": pos_sales,
            "pos_fee": pos_fee,
            "cash_count": cash_count,
            "pos_count": pos_count,
            "split_count": split_count,
            "withdrawal_total": withdrawal_total,
            "withdrawal_amount": withdrawal_amount,
            "deposit_total": deposit_total,
            "deposit_amount": deposit_amount,
            "pos_banking_profit": pos_banking_profit,
            "withdrawal_count": withdrawal_count,
            "deposit_count": deposit_count,
            "prev_cash_carryover": prev_cash_carryover,
            "prev_pos_carryover": prev_pos_carryover,
            "cash_balance_withdrawals": cash_balance_withdrawals,
            "pos_balance_withdrawals": pos_balance_withdrawals,
            "cash_withdrawal_count": cash_withdrawal_count,
            "pos_withdrawal_count": pos_withdrawal_count,
            "cash_balance": cash_balance,
            "pos_balance": pos_balance,
            "total_sales": total_sales,
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


@router.get("/product-sales", response_class=HTMLResponse)
async def product_sales_breakdown(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    category_id: int = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Product sales breakdown - shows sales stats for each product"""
    # Default to last 30 days
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Base query for product sales
    query = db.query(
        models.Product.id,
        models.Product.name,
        models.Category.name.label("category"),
        models.Product.selling_price,
        models.Product.cost_price,
        models.Product.shop_quantity,
        models.Product.store_quantity,
        func.count(models.SaleItem.id).label("sale_count"),
        func.sum(models.SaleItem.quantity).label("qty_sold"),
        func.sum(models.SaleItem.units_deducted).label("units_sold"),
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue"),
        func.sum(models.SaleItem.cost_price).label("total_cost"),
        func.sum(case((models.SaleItem.sale_type == 'pack', models.SaleItem.quantity), else_=0)).label("packs_sold"),
        func.sum(case((models.SaleItem.sale_type == 'unit', models.SaleItem.quantity), else_=0)).label("units_sold_direct")
    ).outerjoin(
        models.SaleItem, models.Product.id == models.SaleItem.product_id
    ).outerjoin(
        models.Sale,
        (models.SaleItem.sale_id == models.Sale.id) &
        (func.date(models.Sale.created_at) >= start) &
        (func.date(models.Sale.created_at) <= end)
    ).join(
        models.Category, models.Product.category_id == models.Category.id
    )

    if category_id:
        query = query.filter(models.Product.category_id == category_id)

    query = query.group_by(
        models.Product.id, models.Product.name, models.Category.name,
        models.Product.selling_price, models.Product.cost_price,
        models.Product.shop_quantity, models.Product.store_quantity
    ).order_by(
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).desc().nullslast()
    )

    products = query.all()

    # Get categories for filter
    categories = db.query(models.Category).order_by(models.Category.name).all()

    report_data = []
    total_revenue = 0
    total_cost = 0
    total_units = 0

    for p in products:
        revenue = p.revenue or 0
        cost = p.total_cost or 0
        profit = revenue - cost
        margin = (profit / revenue * 100) if revenue > 0 else 0
        units = p.units_sold or p.qty_sold or 0

        total_revenue += revenue
        total_cost += cost
        total_units += units

        report_data.append({
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "selling_price": p.selling_price,
            "cost_price": p.cost_price,
            "shop_quantity": p.shop_quantity or 0,
            "store_quantity": p.store_quantity or 0,
            "sale_count": p.sale_count or 0,
            "qty_sold": p.qty_sold or 0,
            "units_sold": units,
            "packs_sold": p.packs_sold or 0,
            "units_sold_direct": p.units_sold_direct or 0,
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "margin": round(margin, 1)
        })

    total_profit = total_revenue - total_cost
    total_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

    return templates.TemplateResponse(
        request, "reports/product_sales.html", {
            "user": user,
            "is_admin": user.role == "admin",
            "report_data": report_data,
            "categories": categories,
            "selected_category": category_id,
            "start_date": start_date,
            "end_date": end_date,
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "total_profit": total_profit,
            "total_margin": round(total_margin, 1),
            "total_units": total_units
        }
    )


@router.get("/product-sales/{product_id}", response_class=HTMLResponse)
async def product_sales_detail(
    request: Request,
    product_id: int,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Detailed sales history for a specific product"""
    # Default to last 30 days
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Get product
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Product not found")

    # Get all sales for this product
    sales_query = db.query(
        models.SaleItem,
        models.Sale.created_at,
        models.Sale.id.label("sale_id"),
        models.Sale.payment_method,
        models.User.username
    ).join(
        models.Sale, models.SaleItem.sale_id == models.Sale.id
    ).join(
        models.User, models.Sale.user_id == models.User.id
    ).filter(
        models.SaleItem.product_id == product_id,
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).order_by(
        models.Sale.created_at.desc()
    )

    sales = sales_query.all()

    # Calculate summary stats
    total_qty = 0
    total_units = 0
    total_revenue = 0
    total_cost = 0
    unit_sales_count = 0
    pack_sales_count = 0

    sale_items = []
    for item in sales:
        sale_item = item.SaleItem
        qty = sale_item.quantity
        units = sale_item.units_deducted or qty
        revenue = sale_item.unit_price * qty
        cost = sale_item.cost_price

        total_qty += qty
        total_units += units
        total_revenue += revenue
        total_cost += cost

        if sale_item.sale_type == 'pack':
            pack_sales_count += 1
        else:
            unit_sales_count += 1

        # Get pack name if available
        pack_name = None
        if sale_item.pack_id and sale_item.pack:
            pack_name = sale_item.pack.name

        sale_items.append({
            "sale_id": item.sale_id,
            "date": item.created_at,
            "username": item.username,
            "payment_method": item.payment_method,
            "quantity": qty,
            "units_deducted": units,
            "unit_price": sale_item.unit_price,
            "total": revenue,
            "cost": cost,
            "profit": revenue - cost,
            "sale_type": sale_item.sale_type,
            "pack_name": pack_name
        })

    total_profit = total_revenue - total_cost
    total_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

    # Get daily breakdown
    daily_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.sum(models.SaleItem.quantity).label("qty"),
        func.sum(models.SaleItem.units_deducted).label("units"),
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue")
    ).join(
        models.Sale, models.SaleItem.sale_id == models.Sale.id
    ).filter(
        models.SaleItem.product_id == product_id,
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        func.date(models.Sale.created_at)
    ).order_by(
        func.date(models.Sale.created_at).desc()
    ).all()

    daily_data = [
        {
            "date": str(d.sale_date),
            "qty": d.qty or 0,
            "units": d.units or d.qty or 0,
            "revenue": d.revenue or 0
        }
        for d in daily_stats
    ]

    return templates.TemplateResponse(
        request, "reports/product_sales_detail.html", {
            "user": user,
            "is_admin": user.role == "admin",
            "product": product,
            "sale_items": sale_items,
            "daily_data": daily_data,
            "start_date": start_date,
            "end_date": end_date,
            "total_qty": total_qty,
            "total_units": total_units,
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "total_profit": total_profit,
            "total_margin": round(total_margin, 1),
            "unit_sales_count": unit_sales_count,
            "pack_sales_count": pack_sales_count,
            "sale_count": len(sale_items)
        }
    )


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

    # Get individual POS sales to calculate fee per transaction (including split payments)
    pos_sales_list = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        models.Sale.total_amount,
        models.Sale.payment_method,
        models.Sale.pos_amount
    ).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end,
        models.Sale.payment_method.in_(['pos', 'split'])
    ).all()

    # Calculate fees per transaction and group by date
    pos_fees_by_date = {}
    for sale in pos_sales_list:
        date_str = str(sale.sale_date)
        pos_amt = sale.total_amount if sale.payment_method == 'pos' else sale.pos_amount
        fee = calculate_pos_fee_per_transaction(pos_amt, pos_fee_percentage, pos_fee_cap)
        pos_fees_by_date[date_str] = pos_fees_by_date.get(date_str, 0) + fee

    # Get sales by date and payment method (including split payments)
    sales_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.sum(case(
            (models.Sale.payment_method == 'cash', models.Sale.total_amount),
            (models.Sale.payment_method == 'split', models.Sale.cash_amount),
            else_=0
        )).label("cash_sales"),
        func.sum(case(
            (models.Sale.payment_method == 'pos', models.Sale.total_amount),
            (models.Sale.payment_method == 'split', models.Sale.pos_amount),
            else_=0
        )).label("pos_sales"),
        func.count(case((models.Sale.payment_method == 'cash', 1), else_=None)).label("cash_count"),
        func.count(case((models.Sale.payment_method == 'pos', 1), else_=None)).label("pos_count"),
        func.count(case((models.Sale.payment_method == 'split', 1), else_=None)).label("split_count")
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
            "pos_count": row.pos_count or 0,
            "split_count": row.split_count or 0
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

    # Get balance withdrawals by date
    balance_withdrawal_stats = db.query(
        func.date(models.BalanceWithdrawal.created_at).label("withdrawal_date"),
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'cash', models.BalanceWithdrawal.amount), else_=0)).label("cash_withdrawals"),
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'pos', models.BalanceWithdrawal.amount), else_=0)).label("pos_withdrawals")
    ).filter(
        func.date(models.BalanceWithdrawal.created_at) >= start,
        func.date(models.BalanceWithdrawal.created_at) <= end
    ).group_by(
        func.date(models.BalanceWithdrawal.created_at)
    ).all()

    balance_withdrawals_by_date = {}
    for row in balance_withdrawal_stats:
        balance_withdrawals_by_date[str(row.withdrawal_date)] = {
            "cash_withdrawals": row.cash_withdrawals or 0,
            "pos_withdrawals": row.pos_withdrawals or 0
        }

    # Get all unique dates
    all_dates = sorted(
        set(list(sales_by_date.keys()) + list(pos_banking_by_date.keys()) + list(carryover_by_date.keys()) + list(pos_fees_by_date.keys()) + list(balance_withdrawals_by_date.keys())),
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
        balance_withdrawals = balance_withdrawals_by_date.get(date_str, {"cash_withdrawals": 0, "pos_withdrawals": 0})

        cash_carryover = carryover.cash_carryover if carryover else 0
        pos_carryover = carryover.pos_carryover if carryover else 0

        # Get POS sales fee for this date (calculated per transaction, already summed)
        pos_sales_fee = pos_fees_by_date.get(date_str, 0)

        # Calculate cash and POS balances for the day
        # Cash: Cash Sales + Deposit Total (cash received) - Withdrawal Amount (cash given out) + Carryover - Balance Withdrawals
        # POS: POS Sales - POS Fee + Withdrawal Total (received from customer) - Deposit Amount (transferred to customer) + Carryover - Balance Withdrawals
        cash_balance = (sales["cash_sales"] +
                       pos_banking["deposit_total"] -      # Cash received from customer
                       pos_banking["withdrawal_amount"] -  # Cash given to customer (amount, not total)
                       balance_withdrawals["cash_withdrawals"] +  # Balance withdrawn
                       cash_carryover)
        pos_balance = (sales["pos_sales"] -
                      pos_sales_fee +                      # POS transaction fee deducted
                      pos_banking["withdrawal_total"] -    # Full amount from customer's account
                      pos_banking["deposit_amount"] -      # Amount transferred to customer's account
                      balance_withdrawals["pos_withdrawals"] +  # Balance withdrawn
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
            "cash_balance_withdrawals": balance_withdrawals["cash_withdrawals"],
            "pos_balance_withdrawals": balance_withdrawals["pos_withdrawals"],
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
    total_cash_balance_withdrawals = sum(r["cash_balance_withdrawals"] for r in report_data)
    total_pos_balance_withdrawals = sum(r["pos_balance_withdrawals"] for r in report_data)

    # Get the previous day's carryover (day before the report start date)
    prev_day = (start - timedelta(days=1)).isoformat()
    prev_day_carryover = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date == prev_day
    ).first()

    total_cash_carryover = prev_day_carryover.cash_carryover if prev_day_carryover else 0
    total_pos_carryover = prev_day_carryover.pos_carryover if prev_day_carryover else 0

    # Grand balances
    # Cash: Cash Sales + Deposit Total (cash received) - Withdrawal Amount (cash given) + Previous Day's Cash Carryover - Balance Withdrawals
    grand_cash_balance = total_cash_sales + total_deposit_total - total_withdrawal_amount + total_cash_carryover - total_cash_balance_withdrawals
    # POS: POS Sales - POS Fee + Withdrawal Total (from customer) - Deposit Amount (to customer) + Previous Day's POS Carryover - Balance Withdrawals
    grand_pos_balance = total_pos_sales - total_pos_sales_fee + total_withdrawal_total - total_deposit_amount + total_pos_carryover - total_pos_balance_withdrawals

    return templates.TemplateResponse(
        request, "reports/cash_pos_summary.html", {"user": user,
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
            "total_cash_balance_withdrawals": total_cash_balance_withdrawals,
            "total_pos_balance_withdrawals": total_pos_balance_withdrawals,
            "total_cash_carryover": total_cash_carryover,
            "total_pos_carryover": total_pos_carryover,
            "grand_cash_balance": grand_cash_balance,
            "grand_pos_balance": grand_pos_balance,
            "pos_fee_percentage": pos_fee_percentage,
            "pos_fee_cap": pos_fee_cap
        }
    )


@router.get("/daily-product-sales", response_class=HTMLResponse)
async def daily_product_sales(
    request: Request,
    report_date: str = None,
    category_id: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Daily sales summary per product - shows what was sold for each product on a specific day"""
    # Default to today
    if not report_date:
        report_date = date.today().isoformat()

    # Handle empty category_id string
    category_id_int = None
    if category_id and category_id.strip():
        try:
            category_id_int = int(category_id)
        except ValueError:
            pass

    target_date = datetime.strptime(report_date, "%Y-%m-%d").date()

    # Get sales data for the specific date using a subquery
    from sqlalchemy.orm import aliased
    from sqlalchemy import and_

    # Subquery: get sale items only for sales on the target date
    daily_sales_subq = db.query(
        models.SaleItem.product_id,
        func.count(models.SaleItem.id).label("sale_count"),
        func.sum(models.SaleItem.quantity).label("qty_sold"),
        func.sum(models.SaleItem.units_deducted).label("units_sold"),
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue"),
        func.sum(models.SaleItem.cost_price).label("total_cost"),
        func.sum(case((models.SaleItem.sale_type == 'pack', models.SaleItem.quantity), else_=0)).label("packs_sold"),
        func.sum(case((models.SaleItem.sale_type == 'unit', models.SaleItem.quantity), else_=0)).label("units_sold_direct")
    ).join(
        models.Sale, models.SaleItem.sale_id == models.Sale.id
    ).filter(
        func.date(models.Sale.created_at) == target_date
    ).group_by(
        models.SaleItem.product_id
    ).subquery()

    # Main query: join products with the daily sales subquery
    query = db.query(
        models.Product.id,
        models.Product.name,
        models.Category.name.label("category"),
        models.Product.selling_price,
        models.Product.cost_price,
        models.Product.shop_quantity,
        models.Product.store_quantity,
        func.coalesce(daily_sales_subq.c.sale_count, 0).label("sale_count"),
        func.coalesce(daily_sales_subq.c.qty_sold, 0).label("qty_sold"),
        func.coalesce(daily_sales_subq.c.units_sold, 0).label("units_sold"),
        func.coalesce(daily_sales_subq.c.revenue, 0).label("revenue"),
        func.coalesce(daily_sales_subq.c.total_cost, 0).label("total_cost"),
        func.coalesce(daily_sales_subq.c.packs_sold, 0).label("packs_sold"),
        func.coalesce(daily_sales_subq.c.units_sold_direct, 0).label("units_sold_direct")
    ).outerjoin(
        daily_sales_subq, models.Product.id == daily_sales_subq.c.product_id
    ).join(
        models.Category, models.Product.category_id == models.Category.id
    )

    if category_id_int:
        query = query.filter(models.Product.category_id == category_id_int)

    query = query.order_by(
        daily_sales_subq.c.revenue.desc().nullslast()
    )

    products = query.all()

    # Get categories for filter
    categories = db.query(models.Category).order_by(models.Category.name).all()

    # Filter to only show products with sales on this day (or all if no sales)
    report_data = []
    total_revenue = 0
    total_cost = 0
    total_units = 0
    products_with_sales = 0

    for p in products:
        revenue = p.revenue or 0
        cost = p.total_cost or 0
        profit = revenue - cost
        margin = (profit / revenue * 100) if revenue > 0 else 0
        units = p.units_sold or p.qty_sold or 0

        # Only include products that had sales on this day
        if units > 0 or revenue > 0:
            total_revenue += revenue
            total_cost += cost
            total_units += units
            products_with_sales += 1

            report_data.append({
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "selling_price": p.selling_price,
                "cost_price": p.cost_price,
                "shop_quantity": p.shop_quantity or 0,
                "store_quantity": p.store_quantity or 0,
                "sale_count": p.sale_count or 0,
                "qty_sold": p.qty_sold or 0,
                "units_sold": units,
                "packs_sold": p.packs_sold or 0,
                "units_sold_direct": p.units_sold_direct or 0,
                "revenue": revenue,
                "cost": cost,
                "profit": profit,
                "margin": round(margin, 1)
            })

    total_profit = total_revenue - total_cost
    total_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

    # Get transaction count for the day
    transaction_count = db.query(func.count(models.Sale.id)).filter(
        func.date(models.Sale.created_at) == target_date
    ).scalar() or 0

    return templates.TemplateResponse(
        request, "reports/daily_product_sales.html", {
            "user": user,
            "is_admin": user.role == "admin",
            "report_data": report_data,
            "categories": categories,
            "selected_category": category_id_int,
            "report_date": report_date,
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "total_profit": total_profit,
            "total_margin": round(total_margin, 1),
            "total_units": total_units,
            "products_with_sales": products_with_sales,
            "transaction_count": transaction_count
        }
    )


@router.get("/inventory-summary", response_class=HTMLResponse)
async def inventory_summary(
    request: Request,
    category_id: int = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Inventory summary showing total stock, sold, and remaining for each product"""
    # Get all products with their total sold units
    query = db.query(
        models.Product.id,
        models.Product.name,
        models.Category.name.label("category"),
        models.Product.store_quantity,
        models.Product.shop_quantity,
        models.Product.reorder_level,
        func.coalesce(func.sum(models.SaleItem.units_deducted), 0).label("total_sold"),
        func.coalesce(func.sum(models.StockAdjustment.quantity_change), 0).label("total_adjustments")
    ).outerjoin(
        models.SaleItem, models.Product.id == models.SaleItem.product_id
    ).outerjoin(
        models.StockAdjustment, models.Product.id == models.StockAdjustment.product_id
    ).join(
        models.Category, models.Product.category_id == models.Category.id
    )

    if category_id:
        query = query.filter(models.Product.category_id == category_id)

    query = query.group_by(
        models.Product.id, models.Product.name, models.Category.name,
        models.Product.store_quantity, models.Product.shop_quantity,
        models.Product.reorder_level
    ).order_by(models.Product.name)

    products = query.all()

    # Get categories for filter
    categories = db.query(models.Category).order_by(models.Category.name).all()

    report_data = []
    total_stock = 0
    total_sold = 0
    total_remaining = 0

    for p in products:
        remaining = (p.store_quantity or 0) + (p.shop_quantity or 0)
        sold = p.total_sold or 0
        # Total stock = current remaining + total sold (what we've had in total)
        stock = remaining + sold

        total_stock += stock
        total_sold += sold
        total_remaining += remaining

        report_data.append({
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "total_stock": stock,
            "sold": sold,
            "remaining": remaining,
            "store_quantity": p.store_quantity or 0,
            "shop_quantity": p.shop_quantity or 0,
            "reorder_level": p.reorder_level or 0,
            "status": "out" if remaining == 0 else "low" if remaining <= (p.reorder_level or 0) else "ok"
        })

    return templates.TemplateResponse(
        request, "reports/inventory_summary.html", {
            "user": user,
            "is_admin": user.role == "admin",
            "report_data": report_data,
            "categories": categories,
            "selected_category": category_id,
            "total_stock": total_stock,
            "total_sold": total_sold,
            "total_remaining": total_remaining
        }
    )
