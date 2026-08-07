from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta, datetime
from calendar import monthrange
from .. import models, auth
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


def resolve_period(period_type: str, day: str = None, month: str = None):
    """Resolve a period type + reference into (start_date, end_date, label)."""
    period_type = period_type or "daily"

    if period_type == "monthly":
        # month format: YYYY-MM (or YYYY-MM-DD -> take first 7 chars)
        m = month or (day[:7] if day else date.today().strftime("%Y-%m"))
        try:
            year, mon = int(m[:4]), int(m[5:7])
        except ValueError:
            year, mon = date.today().year, date.today().month
        start = date(year, mon, 1)
        end = date(year, mon, monthrange(year, mon)[1])
        label = m
        return start, end, label

    # daily / weekly (and fallback) use a day
    if day:
        try:
            ref = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            ref = date.today()
    else:
        ref = date.today()

    if period_type == "weekly":
        start = ref - timedelta(days=ref.weekday())
        end = start + timedelta(days=6)
        label = f"{start} to {end}"
        return start, end, label

    # default daily
    return ref, ref, str(ref)


def period_sold_and_adj(db: Session, since: date = None, after: date = None):
    """
    Build product -> units-sold and product -> net adjustments maps for dated activity.

    - since: include activity on or after this date (date >= since)
    - after: include activity strictly after this date (date > after)
    """
    sold_map = {}
    adj_map = {}

    sold_query = db.query(
        models.SaleItem.product_id.label("pid"),
        func.sum(models.SaleItem.units_deducted).label("total")
    ).join(models.Sale, models.SaleItem.sale_id == models.Sale.id)

    if since is not None:
        sold_query = sold_query.filter(func.date(models.Sale.created_at) >= since)
    if after is not None:
        sold_query = sold_query.filter(func.date(models.Sale.created_at) > after)

    for row in sold_query.group_by(models.SaleItem.product_id).all():
        sold_map[row.pid] = row.total or 0

    adj_query = db.query(
        models.StockAdjustment.product_id.label("pid"),
        func.sum(models.StockAdjustment.quantity_change).label("total")
    )

    if since is not None:
        adj_query = adj_query.filter(func.date(models.StockAdjustment.created_at) >= since)
    if after is not None:
        adj_query = adj_query.filter(func.date(models.StockAdjustment.created_at) > after)

    for row in adj_query.group_by(models.StockAdjustment.product_id).all():
        adj_map[row.pid] = row.total or 0

    return sold_map, adj_map


def compute_reconciliation_data(db: Session, start: date, end: date):
    """Compute per-product opening stock and system closing stock for a period."""
    products = db.query(models.Product).order_by(models.Product.name).all()

    # Reconstruct stock at a reference time from today's quantities:
    #   qty(reference) = current + units sold after reference - net adj after reference
    # opening uses activity since (>= start) ... -> date >= start added back... note:
    # opening = current + sold(date>=start) - adj(date>=start)
    # closing = current + sold(date>end)    - adj(date>end)
    sold_since_start, adj_since_start = period_sold_and_adj(db, since=start, after=None)
    sold_after_end, adj_after_end = period_sold_and_adj(db, since=None, after=end)

    today = date.today()

    data = []
    for p in products:
        current = (p.store_quantity or 0) + (p.shop_quantity or 0)

        opening = current + sold_since_start.get(p.id, 0) - adj_since_start.get(p.id, 0)

        # If the period ends in the future (only possible the same-day as today),
        # treat today's close as current.
        if end >= today:
            closing = current
        else:
            closing = current + sold_after_end.get(p.id, 0) - adj_after_end.get(p.id, 0)

        data.append({
            "id": p.id,
            "name": p.name,
            "unit": p.unit,
            "cost_price": p.cost_price or 0,
            "selling_price": p.selling_price or 0,
            "opening": opening,
            "system_close": closing,
            "current": current
        })

    return data


def find_existing(db: Session, period_type: str, start: date):
    return db.query(models.StockReconciliation).filter(
        models.StockReconciliation.period_type == period_type,
        models.StockReconciliation.period_start == start
    ).first()


@router.get("", response_class=HTMLResponse)
async def reconciliation_page(
    request: Request,
    period_type: str = None,
    day: str = None,
    month: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    start, end, label = resolve_period(period_type, day, month)
    period_type = period_type or "daily"

    # Load an existing snapshot for this exact period (for prefilling actuals).
    existing = find_existing(db, period_type, start)
    saved_actuals = {}
    if existing:
        for item in existing.items:
            saved_actuals[item.product_id] = {
                "actual": item.actual_close_stock,
                "status": item.quantity_difference
            }

    data = compute_reconciliation_data(db, start, end)

    # Attach saved actuals and compute differences
    rows = []
    total_system_close = 0
    total_actual = 0
    total_qty_diff = 0
    total_value_diff = 0
    for p in data:
        saved = saved_actuals.get(p["id"])
        actual = saved["actual"] if saved else p["system_close"]
        qty_diff = actual - p["system_close"]
        value_diff = qty_diff * p["selling_price"]

        total_system_close += p["system_close"]
        total_actual += actual
        total_qty_diff += qty_diff
        total_value_diff += value_diff

        rows.append({
            "id": p["id"],
            "name": p["name"],
            "unit": p["unit"],
            "opening": p["opening"],
            "system_close": p["system_close"],
            "selling_price": p["selling_price"],
            "actual": actual,
            "qty_diff": qty_diff,
            "value_diff": value_diff,
            "saved": bool(saved)
        })

    auto_balanced = abs(total_qty_diff) < 0.005

    return templates.TemplateResponse(
        request, "reconciliation/index.html", {
            "user": user,
            "is_admin": True,
            "period_type": period_type,
            "start": start,
            "end": end,
            "label": label,
            "day": day or date.today().isoformat(),
            "month": month or start.strftime("%Y-%m"),
            "rows": rows,
            "total_system_close": total_system_close,
            "total_actual": total_actual,
            "total_qty_diff": total_qty_diff,
            "total_value_diff": total_value_diff,
            "existing": existing,
            "auto_balanced": auto_balanced,
            "existing_notes": existing.notes if existing else "",
            "existing_status": existing.status if existing else auto_balanced and "balanced" or "unbalanced"
        }
    )


@router.post("/save", response_class=JSONResponse)
async def save_reconciliation(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    body = await request.json()

    period_type = body.get("period_type", "daily")
    start = datetime.strptime(body.get("start"), "%Y-%m-%d").date()
    end = datetime.strptime(body.get("end"), "%Y-%m-%d").date()
    label = body.get("label", "")
    notes = body.get("notes", "")
    status_override = body.get("status")  # "balanced" | "unbalanced" | None
    actuals = body.get("actuals", {})  # {product_id: value}

    existing = find_existing(db, period_type, start)
    reconciliation = existing
    if not reconciliation:
        reconciliation = models.StockReconciliation(
            period_type=period_type,
            period_start=start,
            period_end=end,
            label=label,
            status="balanced",
            created_by=user.id
        )
        db.add(reconciliation)
        db.flush()
        existing = reconciliation
    else:
        reconciliation.label = label

    # Recompute authoritative opening/closing from live data
    data = compute_reconciliation_data(db, start, end)

    for p in data:
        pid = p["id"]
        raw = actuals.get(str(pid))
        try:
            actual = float(raw) if raw is not None else p["system_close"]
        except (TypeError, ValueError):
            actual = p["system_close"]
        actual = round(actual, 3)
        qty_diff = round(actual - p["system_close"], 3)
        value_diff = round(qty_diff * p["selling_price"], 2)

        # upsert item
        item = existing and next((i for i in existing.items if i.product_id == pid), None)
        if not item:
            item = models.StockReconciliationItem(
                reconciliation_id=reconciliation.id,
                product_id=pid,
                product_name=p["name"],
                selling_price=p["selling_price"]
            )
            db.add(item)
        item.opening_stock = p["opening"]
        item.system_close_stock = p["system_close"]
        item.actual_close_stock = actual
        item.quantity_difference = qty_diff
        item.value_difference = value_diff

    # compute auto status
    total_qty_diff = sum(i.quantity_difference for i in reconciliation.items)
    auto_status = "balanced" if abs(total_qty_diff) < 0.005 else "unbalanced"
    reconciliation.status = status_override or auto_status
    reconciliation.notes = notes

    db.commit()

    return {"success": True, "id": reconciliation.id, "status": reconciliation.status}


@router.get("/history", response_class=HTMLResponse)
async def reconciliation_history(
    request: Request,
    period_type: str = None,
    status: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    query = db.query(models.StockReconciliation).order_by(
        models.StockReconciliation.period_start.desc()
    )

    if period_type:
        query = query.filter(models.StockReconciliation.period_type == period_type)
    if status:
        query = query.filter(models.StockReconciliation.status == status)

    reconciliations = query.all()

    return templates.TemplateResponse(
        request, "reconciliation/history.html", {
            "user": user,
            "is_admin": True,
            "reconciliations": reconciliations,
            "filter_type": period_type,
            "filter_status": status
        }
    )


@router.get("/{rec_id}", response_class=HTMLResponse)
async def reconciliation_detail(
    request: Request,
    rec_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    rec = db.query(models.StockReconciliation).filter(
        models.StockReconciliation.id == rec_id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Reconciliation not found")

    total_qty_diff = sum(i.quantity_difference for i in rec.items)
    total_value_diff = sum(i.value_difference for i in rec.items)

    return templates.TemplateResponse(
        request, "reconciliation/detail.html", {
            "user": user,
            "is_admin": True,
            "rec": rec,
            "sender": rec.creator.username if rec.creator else "-",
            "total_qty_diff": total_qty_diff,
            "total_value_diff": total_value_diff
        }
    )


@router.post("/{rec_id}/delete", response_class=HTMLResponse)
async def delete_reconciliation(
    rec_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    rec = db.query(models.StockReconciliation).filter(
        models.StockReconciliation.id == rec_id
    ).first()
    if rec:
        db.delete(rec)
        db.commit()
    return RedirectResponse(url="/reconciliation/history", status_code=302)