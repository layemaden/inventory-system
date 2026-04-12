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

    report_data = []
    for row in daily_stats:
        date_str = str(row.sale_date)
        carryover = carryover_by_date.get(date_str)
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
            "notes": carryover.notes if carryover else ""
        })

    # Calculate totals
    total_transactions = sum(r["transactions"] for r in report_data)
    total_sales = sum(r["total_sales"] for r in report_data)
    total_items = sum(r["items_sold"] for r in report_data)
    total_cash = sum(r["cash_total"] for r in report_data)
    total_pos = sum(r["pos_total"] for r in report_data)

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
            "total_pos": total_pos
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

    # Query profit by date
    profit_stats = db.query(
        func.date(models.Sale.created_at).label("sale_date"),
        func.sum(models.SaleItem.unit_price * models.SaleItem.quantity).label("revenue"),
        func.sum(models.SaleItem.cost_price).label("cost")  # cost_price is already total cost
    ).join(models.SaleItem).filter(
        func.date(models.Sale.created_at) >= start,
        func.date(models.Sale.created_at) <= end
    ).group_by(
        func.date(models.Sale.created_at)
    ).order_by(
        func.date(models.Sale.created_at).desc()
    ).all()

    report_data = []
    for row in profit_stats:
        revenue = row.revenue or 0
        cost = row.cost or 0
        profit = revenue - cost
        margin = (profit / revenue * 100) if revenue > 0 else 0

        report_data.append({
            "date": str(row.sale_date),
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "margin": round(margin, 1)
        })

    # Calculate totals
    total_revenue = sum(r["revenue"] for r in report_data)
    total_cost = sum(r["cost"] for r in report_data)
    total_profit = total_revenue - total_cost
    total_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

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
