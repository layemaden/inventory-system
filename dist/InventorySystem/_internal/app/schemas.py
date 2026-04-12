from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# User schemas
class UserBase(BaseModel):
    username: str
    role: str = "staff"


class UserCreate(UserBase):
    pin: Optional[str] = None
    password: Optional[str] = None


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Category schemas
class CategoryBase(BaseModel):
    name: str
    description: Optional[str] = None


class CategoryCreate(CategoryBase):
    pass


class CategoryResponse(CategoryBase):
    id: int

    class Config:
        from_attributes = True


# Product schemas
class ProductBase(BaseModel):
    name: str
    category_id: int
    selling_price: float
    store_quantity: float = 0
    shop_quantity: float = 0
    reorder_level: int = 10
    unit: str = "piece"


class ProductCreate(ProductBase):
    cost_price: float


class ProductResponse(ProductBase):
    id: int
    stock_quantity: float = 0  # Total of store + shop
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductAdminResponse(ProductResponse):
    cost_price: float


# Sale schemas
class SaleItemCreate(BaseModel):
    product_id: int
    quantity: float


class SaleCreate(BaseModel):
    items: List[SaleItemCreate]


class SaleItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: float
    unit_price: float
    product_name: Optional[str] = None

    class Config:
        from_attributes = True


class SaleItemAdminResponse(SaleItemResponse):
    cost_price: float


class SaleResponse(BaseModel):
    id: int
    total_amount: float
    created_at: datetime
    items: List[SaleItemResponse]

    class Config:
        from_attributes = True


# Stock adjustment schemas
class StockAdjustmentCreate(BaseModel):
    product_id: int
    quantity_change: float
    location: str = "store"  # "store" or "shop"
    reason: Optional[str] = None


class StockAdjustmentResponse(BaseModel):
    id: int
    product_id: int
    quantity_change: float
    location: str = "store"
    reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Report schemas
class DailySalesReport(BaseModel):
    date: str
    total_sales: float
    total_transactions: int
    items_sold: int


class ProfitReport(BaseModel):
    date: str
    revenue: float
    cost: float
    profit: float
    margin_percentage: float


class LowStockAlert(BaseModel):
    product_id: int
    product_name: str
    current_stock: int
    reorder_level: int
    category_name: str
