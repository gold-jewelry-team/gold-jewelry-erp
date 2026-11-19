"""Immutable-at-completion sales and per-line pricing snapshots."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'COMPLETED', 'VOID')", name="ck_sales_status"),
        CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_sales_payment_method"),
        CheckConstraint("length(currency_code) = 3", name="ck_sales_currency_code_length"),
        Index("ix_sales_company_site_created", "company_id", "site_id", "created_at"),
        UniqueConstraint("site_id", "sale_no", name="uq_sales_site_sale_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    sale_no: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT", server_default="DRAFT")
    payment_method: Mapped[str] = mapped_column(String(12), nullable=False, default="CASH", server_default="CASH")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    card_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    final_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SaleLine(Base):
    __tablename__ = "sale_lines"
    __table_args__ = (
        CheckConstraint("gross_weight >= 0", name="ck_sale_lines_gross_weight_nonnegative"),
        CheckConstraint("net_weight >= 0", name="ck_sale_lines_net_weight_nonnegative"),
        CheckConstraint("labor_fee >= 0", name="ck_sale_lines_labor_fee_nonnegative"),
        CheckConstraint("trade_in_source IS NULL OR trade_in_source IN ('LOCAL', 'EXTERNAL')", name="ck_sale_lines_trade_in_source"),
        CheckConstraint("trade_in_ratio IS NULL OR (trade_in_ratio > 0 AND trade_in_ratio <= 1)", name="ck_sale_lines_trade_in_ratio"),
        CheckConstraint("currency_code IS NULL OR length(currency_code) = 3", name="ck_sale_lines_currency_code_length"),
        Index("ix_sale_lines_sale_id", "sale_id"),
        UniqueConstraint("sale_id", "line_no", name="uq_sale_lines_sale_line_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False)
    line_no: Mapped[int] = mapped_column(nullable=False)
    product_code_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    barcode_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    gross_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    net_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    weight_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    labor_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))

    # Price snapshot: values and units are copied at transaction time. Optional
    # FKs only point back to the source history row; snapshots remain readable.
    sell_gold_price_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("gold_prices.id", ondelete="RESTRICT"), nullable=True)
    sell_gold_price_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    sell_gold_price_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    buy_gold_price_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("gold_prices.id", ondelete="RESTRICT"), nullable=True)
    buy_gold_price_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    buy_gold_price_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    price_currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    price_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trade_in_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    old_gold_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    trade_in_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    adjusted_old_gold_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    pricing_rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    card_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    final_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
