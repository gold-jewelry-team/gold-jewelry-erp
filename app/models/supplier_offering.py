"""Supplier-to-category and supplier-to-product catalog relationships."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKeyConstraint, Index, Numeric, String,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SupplierCategoryOffering(Base):
    __tablename__ = "supplier_category_offerings"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'PAUSED', 'STOPPED')", name="ck_supplier_category_offerings_status"),
        UniqueConstraint("company_id", "supplier_id", "category_id", name="uq_supplier_category_offering"),
        ForeignKeyConstraint(["supplier_id", "company_id"], ["suppliers.id", "suppliers.company_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["category_id", "company_id"], ["product_categories.id", "product_categories.company_id"], ondelete="RESTRICT"),
        Index("ix_supplier_category_offerings_company_category", "company_id", "category_id", "status"),
        Index("ix_supplier_category_offerings_supplier", "company_id", "supplier_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ACTIVE", server_default="ACTIVE")
    is_preferred: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    supplier_category_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SupplierProductOffering(Base):
    __tablename__ = "supplier_product_offerings"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'PAUSED', 'STOPPED')", name="ck_supplier_product_offerings_status"),
        CheckConstraint("quoted_unit_cost IS NULL OR quoted_unit_cost >= 0", name="ck_supplier_product_offerings_cost_nonnegative"),
        CheckConstraint("min_order_quantity IS NULL OR min_order_quantity > 0", name="ck_supplier_product_offerings_min_qty_positive"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_supplier_product_offerings_lead_time_nonnegative"),
        UniqueConstraint("company_id", "supplier_id", "product_id", name="uq_supplier_product_offering"),
        ForeignKeyConstraint(["supplier_id", "company_id"], ["suppliers.id", "suppliers.company_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], ondelete="RESTRICT"),
        Index("ix_supplier_product_offerings_company_product", "company_id", "product_id", "status"),
        Index("ix_supplier_product_offerings_supplier", "company_id", "supplier_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    supplier_product_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quoted_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    min_order_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ACTIVE", server_default="ACTIVE")
    is_preferred: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
