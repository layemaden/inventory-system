from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from .database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    STAFF = "staff"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    pin = Column(String(255), nullable=True)  # Hashed PIN for staff
    password = Column(String(255), nullable=True)  # Hashed password for admin
    role = Column(String(20), default=UserRole.STAFF)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    sales = relationship("Sale", back_populates="user")
    stock_adjustments = relationship("StockAdjustment", back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    cost_price = Column(Float, nullable=False)  # Cost per unit (Admin only)
    selling_price = Column(Float, nullable=False)  # Price per unit
    pack_size = Column(Integer, default=1)  # Units per pack (e.g., 12 for a dozen)
    pack_price = Column(Float, nullable=True)  # Price per pack (discounted)
    store_quantity = Column(Float, default=0)  # Quantity in store/warehouse (in units)
    shop_quantity = Column(Float, default=0)   # Quantity in shop for sale (in units)
    reorder_level = Column(Integer, default=10)  # Alert when total below this

    @property
    def stock_quantity(self):
        """Total stock across store and shop (in units)"""
        return (self.store_quantity or 0) + (self.shop_quantity or 0)

    @property
    def shop_packs(self):
        """Number of full packs available in shop"""
        if self.pack_size and self.pack_size > 1:
            return int(self.shop_quantity // self.pack_size)
        return 0

    unit = Column(String(50), default="piece")  # piece, pack, bottle, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    category = relationship("Category", back_populates="products")
    sale_items = relationship("SaleItem", back_populates="product")
    stock_adjustments = relationship("StockAdjustment", back_populates="product")


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="sales")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Float, nullable=False)  # Quantity sold (in units or packs depending on sale_type)
    unit_price = Column(Float, nullable=False)  # Price per unit/pack at time of sale
    cost_price = Column(Float, nullable=False)  # Cost for profit calculation (total cost)
    sale_type = Column(String(10), default="unit")  # "unit" or "pack"
    units_deducted = Column(Float, nullable=False, default=0)  # Actual units removed from inventory

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product", back_populates="sale_items")


class StockAdjustment(Base):
    __tablename__ = "stock_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quantity_change = Column(Float, nullable=False)  # Positive for restock, negative for reduction
    location = Column(String(20), default="store")  # "store" or "shop"
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="stock_adjustments")
    user = relationship("User", back_populates="stock_adjustments")
