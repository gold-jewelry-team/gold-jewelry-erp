"""Product master data for individually barcoded jewelry items."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductCategory(Base):
    __tablename__ = "product_categories"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_product_categories_company_code"),
        CheckConstraint("length(code) > 0", name="ck_product_categories_code_nonempty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Product(Base):
    """One row represents one jewelry item; barcode is unique per company."""
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("company_id", "product_code", name="uq_products_company_code"),
        UniqueConstraint("company_id", "barcode", name="uq_products_company_barcode"),
        CheckConstraint("length(product_code) > 0", name="ck_products_code_nonempty"),
        CheckConstraint("length(name) > 0", name="ck_products_name_nonempty"),
        CheckConstraint("gross_weight >= 0", name="ck_products_gross_weight_nonnegative"),
        CheckConstraint("net_weight >= 0", name="ck_products_net_weight_nonnegative"),
        CheckConstraint("labor_fee >= 0", name="ck_products_labor_fee_nonnegative"),
        CheckConstraint("net_weight <= gross_weight", name="ck_products_net_not_over_gross"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=True, index=True)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    material_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gross_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    net_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    weight_unit_code: Mapped[str] = mapped_column(String(20), nullable=False, default="QIAN", server_default="QIAN")
    labor_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    chain_length: Mapped[str | None] = mapped_column(String(40), nullable=True)
    style_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
