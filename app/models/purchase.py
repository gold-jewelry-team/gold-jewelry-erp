"""Purchase orders and line-level receiving records."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Purchase(Base):
    __tablename__ = "purchases"
    __table_args__ = (
        UniqueConstraint("company_id", "purchase_no", name="uq_purchases_company_no"),
        CheckConstraint("status IN ('DRAFT', 'ORDERED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'CANCELLED')", name="ck_purchases_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    purchase_no: Mapped[str] = mapped_column(String(50), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT", server_default="DRAFT")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_lines_quantity_positive"),
        CheckConstraint("received_quantity >= 0 AND received_quantity <= quantity", name="ck_purchase_lines_received_quantity"),
        CheckConstraint("unit_cost >= 0", name="ck_purchase_lines_unit_cost_nonnegative"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_purchase_lines_weight_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("purchases.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=Decimal("1"))
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=Decimal("0"), server_default="0")
    weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    weight_unit_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
