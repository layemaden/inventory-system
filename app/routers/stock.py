from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models, auth
from ..database import get_db

router = APIRouter(prefix="/stock", tags=["stock"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def stock_overview(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    products = db.query(models.Product).join(models.Category).order_by(
        (models.Product.store_quantity + models.Product.shop_quantity).asc()
    ).all()

    # Get low stock count (total stock below reorder level)
    low_stock_count = db.query(models.Product).filter(
        (models.Product.store_quantity + models.Product.shop_quantity) <= models.Product.reorder_level
    ).count()

    return templates.TemplateResponse(
        "stock/overview.html",
        {
            "request": request,
            "products": products,
            "user": user,
            "is_admin": user.role == "admin",
            "low_stock_count": low_stock_count
        }
    )


@router.get("/alerts", response_class=HTMLResponse)
async def stock_alerts(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    low_stock_products = db.query(models.Product).join(models.Category).filter(
        (models.Product.store_quantity + models.Product.shop_quantity) <= models.Product.reorder_level
    ).order_by(
        (models.Product.store_quantity + models.Product.shop_quantity).asc()
    ).all()

    return templates.TemplateResponse(
        "stock/alerts.html",
        {
            "request": request,
            "products": low_stock_products,
            "user": user,
            "is_admin": user.role == "admin"
        }
    )


@router.get("/api/alerts", response_class=JSONResponse)
async def stock_alerts_api(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    low_stock_products = db.query(models.Product).join(models.Category).filter(
        (models.Product.store_quantity + models.Product.shop_quantity) <= models.Product.reorder_level
    ).order_by(
        (models.Product.store_quantity + models.Product.shop_quantity).asc()
    ).all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category.name,
            "store_quantity": p.store_quantity,
            "shop_quantity": p.shop_quantity,
            "stock_quantity": p.stock_quantity,
            "reorder_level": p.reorder_level,
            "is_critical": p.stock_quantity == 0
        }
        for p in low_stock_products
    ]


@router.get("/{product_id}/adjust", response_class=HTMLResponse)
async def adjust_stock_page(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    adjustments = db.query(models.StockAdjustment).filter(
        models.StockAdjustment.product_id == product_id
    ).order_by(
        models.StockAdjustment.created_at.desc()
    ).limit(20).all()

    return templates.TemplateResponse(
        "stock/adjust.html",
        {
            "request": request,
            "product": product,
            "adjustments": adjustments,
            "user": user
        }
    )


@router.post("/{product_id}/adjust")
async def adjust_stock(
    request: Request,
    product_id: int,
    quantity_change: float = Form(...),
    location: str = Form("store"),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check current quantity for the specified location
    current_qty = product.store_quantity if location == "store" else product.shop_quantity
    new_quantity = current_qty + quantity_change

    if new_quantity < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reduce {location} stock below 0. Current {location} stock: {current_qty}"
        )

    # Create adjustment record
    adjustment = models.StockAdjustment(
        product_id=product_id,
        user_id=user.id,
        quantity_change=quantity_change,
        location=location,
        reason=reason
    )
    db.add(adjustment)

    # Update product stock for the specified location
    if location == "store":
        product.store_quantity = new_quantity
    else:
        product.shop_quantity = new_quantity
    db.commit()

    return RedirectResponse(url=f"/stock/{product_id}/adjust", status_code=302)


@router.post("/{product_id}/transfer")
async def transfer_stock(
    request: Request,
    product_id: int,
    quantity: float = Form(...),
    direction: str = Form(...),  # "to_shop" or "to_store"
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Transfer stock between store and shop"""
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Transfer quantity must be positive")

    if direction == "to_shop":
        if product.store_quantity < quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient store stock. Available: {product.store_quantity}"
            )
        product.store_quantity -= quantity
        product.shop_quantity += quantity
        reason = f"Transfer to shop ({quantity})"
    elif direction == "to_store":
        if product.shop_quantity < quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient shop stock. Available: {product.shop_quantity}"
            )
        product.shop_quantity -= quantity
        product.store_quantity += quantity
        reason = f"Transfer to store ({quantity})"
    else:
        raise HTTPException(status_code=400, detail="Invalid transfer direction")

    # Create adjustment records for audit trail
    adjustment = models.StockAdjustment(
        product_id=product_id,
        user_id=user.id,
        quantity_change=0,  # Net change is 0 for transfers
        location="transfer",
        reason=reason
    )
    db.add(adjustment)
    db.commit()

    return RedirectResponse(url=f"/stock/{product_id}/adjust", status_code=302)


@router.get("/history", response_class=HTMLResponse)
async def stock_history(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    adjustments = db.query(models.StockAdjustment).join(
        models.Product
    ).join(
        models.User
    ).order_by(
        models.StockAdjustment.created_at.desc()
    ).limit(100).all()

    return templates.TemplateResponse(
        "stock/history.html",
        {
            "request": request,
            "adjustments": adjustments,
            "user": user
        }
    )
