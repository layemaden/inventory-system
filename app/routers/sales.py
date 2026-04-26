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
from ..config import settings

router = APIRouter(prefix="/sales", tags=["sales"])
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


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
        request, "sales/pos.html", {"products": products,
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
            "pack_size": p.pack_size or 1,  # Legacy field for backwards compatibility
            "pack_price": p.pack_price,  # Legacy field for backwards compatibility
            "packs": [
                {
                    "id": pack.id,
                    "name": pack.name,
                    "pack_size": pack.pack_size,
                    "pack_price": pack.pack_price
                }
                for pack in p.packs
            ],
            "shop_quantity": p.shop_quantity,
            "shop_packs": p.shop_packs,
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
    payment_method = body.get("payment_method", "cash")  # "cash", "pos", or "split"
    cash_amount = body.get("cash_amount", 0) or 0
    pos_amount = body.get("pos_amount", 0) or 0
    change_owed = body.get("change_owed", 0) or 0
    change_customer_name = body.get("change_customer_name", "")
    pos_cashback = body.get("pos_cashback", 0) or 0  # Cash given back from POS overpayment

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

        sale_type = item.get("sale_type", "unit")  # "unit" or "pack"
        pack_id = item.get("pack_id")  # New: reference to ProductPack
        quantity = item["quantity"]

        # Calculate units to deduct based on sale type
        if sale_type == "pack":
            # Try to get pack details from ProductPack table
            if pack_id:
                pack = db.query(models.ProductPack).filter(models.ProductPack.id == pack_id).first()
                if pack:
                    pack_size = pack.pack_size
                    price_per_item = pack.pack_price
                else:
                    # Fallback to legacy pack data
                    pack_size = product.pack_size or 1
                    price_per_item = product.pack_price or (product.selling_price * pack_size)
            else:
                # Legacy: use product's pack_size and pack_price
                pack_size = product.pack_size or 1
                price_per_item = product.pack_price or (product.selling_price * pack_size)

            units_to_deduct = quantity * pack_size
            cost_for_item = product.cost_price * pack_size  # Cost per pack
        else:
            pack_id = None  # Ensure pack_id is None for unit sales
            units_to_deduct = quantity
            price_per_item = product.selling_price
            cost_for_item = product.cost_price

        # Check shop stock (in units)
        if product.shop_quantity < units_to_deduct:
            if sale_type == "pack":
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient shop stock for {product.name}. Need {units_to_deduct} units for {quantity} pack(s), but only {product.shop_quantity} available"
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient shop stock for {product.name}. Available in shop: {product.shop_quantity}"
                )

        item_total = price_per_item * quantity
        total_amount += item_total

        sale_items.append({
            "product": product,
            "quantity": quantity,
            "unit_price": price_per_item,
            "cost_price": cost_for_item * quantity,  # Total cost for profit calculation
            "sale_type": sale_type,
            "pack_id": pack_id,
            "units_to_deduct": units_to_deduct
        })

    # Handle split payment validation
    if payment_method == "split":
        if cash_amount + pos_amount < total_amount:
            raise HTTPException(
                status_code=400,
                detail=f"Split payment total (N{cash_amount + pos_amount:,.0f}) is less than sale total (N{total_amount:,.0f})"
            )
    elif payment_method == "cash":
        cash_amount = total_amount
        pos_amount = 0
    else:  # pos
        cash_amount = 0
        pos_amount = total_amount

    # For POS payments, validate cashback doesn't exceed POS amount minus sale total
    if payment_method == 'pos' and pos_cashback > 0:
        if pos_cashback > (pos_amount - total_amount):
            raise HTTPException(
                status_code=400,
                detail=f"Cashback (N{pos_cashback:,.0f}) cannot exceed POS overpayment (N{pos_amount - total_amount:,.0f})"
            )

    # Create sale
    sale = models.Sale(
        user_id=user.id,
        total_amount=total_amount,
        payment_method=payment_method,
        cash_amount=cash_amount,
        pos_amount=pos_amount,
        change_owed=change_owed,
        change_collected=0 if change_owed > 0 else 1,  # Pending if change is owed
        change_customer_name=change_customer_name[:100] if change_customer_name else None,
        pos_cashback=pos_cashback
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
            cost_price=item_data["cost_price"],
            sale_type=item_data["sale_type"],
            pack_id=item_data.get("pack_id"),
            units_deducted=item_data["units_to_deduct"]
        )
        db.add(sale_item)

        # Deduct units from shop stock
        item_data["product"].shop_quantity -= item_data["units_to_deduct"]

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
    user: models.User = Depends(auth.require_admin)
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
        request, "sales/history.html", {"sales": sales,
            "user": user,
            "selected_date": date_str or date.today().isoformat()
        }
    )


# ==================== CHANGE COLLECTION ====================

@router.get("/pending-change", response_class=HTMLResponse)
async def pending_change_list(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """View all pending change collections"""
    pending = db.query(models.Sale).filter(
        models.Sale.change_collected == 0,
        models.Sale.change_owed > 0
    ).order_by(models.Sale.created_at.desc()).all()

    return templates.TemplateResponse(
        request, "sales/pending_change.html", {
            "pending_changes": pending,
            "user": user
        }
    )


@router.post("/pending-change/{sale_id}/collect", response_class=JSONResponse)
async def collect_change(
    sale_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Mark change as collected"""
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale.change_collected == 1:
        raise HTTPException(status_code=400, detail="Change already collected")

    sale.change_collected = 1
    sale.change_collected_at = datetime.now()
    sale.change_collected_by = user.id
    db.commit()

    return {"success": True, "message": "Change marked as collected"}


@router.get("/api/pending-change-count", response_class=JSONResponse)
async def pending_change_count(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Get count of pending change collections"""
    count = db.query(func.count(models.Sale.id)).filter(
        models.Sale.change_collected == 0,
        models.Sale.change_owed > 0
    ).scalar() or 0

    total_owed = db.query(func.sum(models.Sale.change_owed)).filter(
        models.Sale.change_collected == 0,
        models.Sale.change_owed > 0
    ).scalar() or 0

    return {"count": count, "total_owed": total_owed}


@router.get("/{sale_id}", response_class=HTMLResponse)
async def sale_detail(
    request: Request,
    sale_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    return templates.TemplateResponse(
        request, "sales/detail.html", {"sale": sale,
            "user": user,
            "is_admin": user.role == "admin"
        }
    )


@router.post("/{sale_id}/delete")
async def delete_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Delete a sale and restore inventory (admin only)"""
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    # Restore inventory for each item
    for item in sale.items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if product:
            # Restore the units that were deducted
            product.shop_quantity += item.units_deducted or item.quantity

    # Delete the sale (cascade deletes sale items)
    db.delete(sale)
    db.commit()

    return RedirectResponse(url="/sales/history", status_code=302)


# ==================== PENDING CART (HOLD/RESUME) ====================

@router.post("/cart/hold", response_class=JSONResponse)
async def hold_cart(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Hold the current cart for later"""
    body = await request.json()
    items = body.get("items", [])
    customer_note = body.get("customer_note", "")

    if not items:
        raise HTTPException(status_code=400, detail="No items to hold")

    # Calculate total
    total_amount = sum(item.get("price", 0) * item.get("quantity", 0) for item in items)

    # Create pending cart
    pending_cart = models.PendingCart(
        user_id=user.id,
        customer_note=customer_note[:200] if customer_note else None,
        total_amount=total_amount
    )
    db.add(pending_cart)
    db.flush()

    # Add items to pending cart
    for item in items:
        cart_item = models.PendingCartItem(
            cart_id=pending_cart.id,
            product_id=item["product_id"],
            quantity=item["quantity"],
            unit_price=item["price"],
            sale_type=item.get("sale_type", "unit"),
            pack_id=item.get("pack_id"),
            pack_size=item.get("pack_size", 1)
        )
        db.add(cart_item)

    db.commit()

    return {
        "success": True,
        "cart_id": pending_cart.id,
        "message": "Cart held successfully"
    }


@router.get("/cart/pending", response_class=JSONResponse)
async def get_pending_carts(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Get all pending carts"""
    carts = db.query(models.PendingCart).order_by(
        models.PendingCart.created_at.desc()
    ).all()

    return [
        {
            "id": cart.id,
            "user": cart.user.username,
            "customer_note": cart.customer_note,
            "total_amount": cart.total_amount,
            "item_count": len(cart.items),
            "created_at": cart.created_at.strftime("%Y-%m-%d %H:%M")
        }
        for cart in carts
    ]


@router.get("/cart/pending/{cart_id}", response_class=JSONResponse)
async def get_pending_cart(
    cart_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Get a specific pending cart with its items"""
    cart = db.query(models.PendingCart).filter(
        models.PendingCart.id == cart_id
    ).first()

    if not cart:
        raise HTTPException(status_code=404, detail="Pending cart not found")

    items = []
    for item in cart.items:
        product = item.product
        pack_name = None
        if item.pack_id and item.pack:
            pack_name = item.pack.name

        items.append({
            "product_id": item.product_id,
            "name": product.name,
            "quantity": item.quantity,
            "price": item.unit_price,
            "sale_type": item.sale_type,
            "pack_id": item.pack_id,
            "pack_name": pack_name,
            "pack_size": item.pack_size,
            "unit": product.unit,
            "current_stock": product.shop_quantity
        })

    return {
        "id": cart.id,
        "user": cart.user.username,
        "customer_note": cart.customer_note,
        "total_amount": cart.total_amount,
        "created_at": cart.created_at.strftime("%Y-%m-%d %H:%M"),
        "items": items
    }


@router.delete("/cart/pending/{cart_id}", response_class=JSONResponse)
async def delete_pending_cart(
    cart_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Delete a pending cart"""
    cart = db.query(models.PendingCart).filter(
        models.PendingCart.id == cart_id
    ).first()

    if not cart:
        raise HTTPException(status_code=404, detail="Pending cart not found")

    db.delete(cart)
    db.commit()

    return {"success": True, "message": "Pending cart deleted"}
