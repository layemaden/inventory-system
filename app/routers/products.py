from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/products", tags=["products"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_products(
    request: Request,
    category_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    query = db.query(models.Product).join(models.Category)

    if category_id:
        query = query.filter(models.Product.category_id == category_id)

    products = query.order_by(models.Product.name).all()
    categories = db.query(models.Category).order_by(models.Category.name).all()

    return templates.TemplateResponse(
        "products/list.html",
        {
            "request": request,
            "products": products,
            "categories": categories,
            "selected_category": category_id,
            "user": user,
            "is_admin": user.role == "admin"
        }
    )


@router.get("/add", response_class=HTMLResponse)
async def add_product_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    categories = db.query(models.Category).order_by(models.Category.name).all()
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "categories": categories, "user": user, "product": None}
    )


@router.post("/add")
async def add_product(
    request: Request,
    name: str = Form(...),
    category_id: int = Form(...),
    cost_price: float = Form(...),
    selling_price: float = Form(...),
    store_quantity: float = Form(0),
    shop_quantity: float = Form(0),
    reorder_level: int = Form(10),
    unit: str = Form("piece"),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    product = models.Product(
        name=name,
        category_id=category_id,
        cost_price=cost_price,
        selling_price=selling_price,
        store_quantity=store_quantity,
        shop_quantity=shop_quantity,
        reorder_level=reorder_level,
        unit=unit
    )
    db.add(product)
    db.commit()
    return RedirectResponse(url="/products", status_code=302)


@router.get("/{product_id}/edit", response_class=HTMLResponse)
async def edit_product_page(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    categories = db.query(models.Category).order_by(models.Category.name).all()
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "categories": categories, "user": user, "product": product}
    )


@router.post("/{product_id}/edit")
async def edit_product(
    request: Request,
    product_id: int,
    name: str = Form(...),
    category_id: int = Form(...),
    cost_price: float = Form(...),
    selling_price: float = Form(...),
    store_quantity: float = Form(0),
    shop_quantity: float = Form(0),
    reorder_level: int = Form(10),
    unit: str = Form("piece"),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.name = name
    product.category_id = category_id
    product.cost_price = cost_price
    product.selling_price = selling_price
    product.store_quantity = store_quantity
    product.shop_quantity = shop_quantity
    product.reorder_level = reorder_level
    product.unit = unit
    db.commit()

    return RedirectResponse(url="/products", status_code=302)


@router.post("/{product_id}/delete")
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    db.delete(product)
    db.commit()
    return RedirectResponse(url="/products", status_code=302)


# Categories
@router.get("/categories", response_class=HTMLResponse)
async def list_categories(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    categories = db.query(models.Category).order_by(models.Category.name).all()
    return templates.TemplateResponse(
        "products/categories.html",
        {"request": request, "categories": categories, "user": user, "is_admin": user.role == "admin"}
    )


@router.post("/categories/add")
async def add_category(
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    category = models.Category(name=name, description=description)
    db.add(category)
    db.commit()
    return RedirectResponse(url="/products/categories", status_code=302)


@router.post("/categories/{category_id}/delete")
async def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Check if category has products
    product_count = db.query(models.Product).filter(models.Product.category_id == category_id).count()
    if product_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete category with products")

    db.delete(category)
    db.commit()
    return RedirectResponse(url="/products/categories", status_code=302)
