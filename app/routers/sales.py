from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
from typing import List
import json
from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/sales", tags=["sales"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def sales_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    # Only show products with shop stock available for sale
    products = db.query(models.Product).filter(
        models.Product.shop_quantity > 0
    ).order_by(models.Product.name).all()

    categories = db.query(models.Category).order_by(models.Category.name).all()

    return templates.TemplateResponse(
        "sales/pos.html",
        {
            "request": request,
            "products": products,
            "categories": categories,
            "user": user
        }
    )


@router.get("/api/products", response_class=JSONResponse)
async def get_products_api(
    category_id: int = None,
    search: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    # Only return products with shop stock available
    query = db.query(models.Product).filter(models.Product.shop_quantity > 0)

    if category_id:
        query = query.filter(models.Product.category_id == category_id)

    if search:
        query = query.filter(models.Product.name.ilike(f"%{search}%"))

    products = query.order_by(models.Product.name).all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "selling_price": p.selling_price,
            "shop_quantity": p.shop_quantity,
            "stock_quantity": p.stock_quantity,
            "unit": p.unit,
            "category_id": p.category_id
        }
        for p in products
    ]


@router.post("/complete")
async def complete_sale(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    body = await request.json()
    items = body.get("items", [])

    if not items:
        raise HTTPException(status_code=400, detail="No items in cart")

    total_amount = 0
    sale_items = []

    # Validate shop stock and calculate total
    for item in items:
        product = db.query(models.Product).filter(
            models.Product.id == item["product_id"]
        ).first()

        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item['product_id']} not found")

        # Check shop stock (not total stock)
        if product.shop_quantity < item["quantity"]:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient shop stock for {product.name}. Available in shop: {product.shop_quantity}"
            )

        item_total = product.selling_price * item["quantity"]
        total_amount += item_total

        sale_items.append({
            "product": product,
            "quantity": item["quantity"],
            "unit_price": product.selling_price,
            "cost_price": product.cost_price
        })

    # Create sale
    sale = models.Sale(
        user_id=user.id,
        total_amount=total_amount
    )
    db.add(sale)
    db.flush()

    # Create sale items and update stock
    for item_data in sale_items:
        sale_item = models.SaleItem(
            sale_id=sale.id,
            product_id=item_data["product"].id,
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            cost_price=item_data["cost_price"]
        )
        db.add(sale_item)

        # Deduct from shop stock
        item_data["product"].shop_quantity -= item_data["quantity"]

    db.commit()

    return {
        "success": True,
        "sale_id": sale.id,
        "total": total_amount
    }


@router.get("/history", response_class=HTMLResponse)
async def sales_history(
    request: Request,
    date_str: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    query = db.query(models.Sale).order_by(models.Sale.created_at.desc())

    if date_str:
        try:
            filter_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter(func.date(models.Sale.created_at) == filter_date)
        except ValueError:
            pass

    sales = query.limit(100).all()

    return templates.TemplateResponse(
        "sales/history.html",
        {
            "request": request,
            "sales": sales,
            "user": user,
            "selected_date": date_str or date.today().isoformat()
        }
    )


@router.get("/{sale_id}", response_class=HTMLResponse)
async def sale_detail(
    request: Request,
    sale_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    return templates.TemplateResponse(
        "sales/detail.html",
        {
            "request": request,
            "sale": sale,
            "user": user,
            "is_admin": user.role == "admin"
        }
    )
