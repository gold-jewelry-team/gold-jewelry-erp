"""Sales returns and item-level refund snapshots."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SaleReturn(Base):
    __tablename__ = "sale_returns"
    __table_args__ = (
        Index("ix_sale_returns_company_site_created", "company_id", "site_id", "created_at"),
        UniqueConstraint("site_id", "return_no", name="uq_sale_returns_site_return_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    sale_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False)
    return_no: Mapped[str] = mapped_column(String(40), nullable=False)
    settlement_reversal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sale: Mapped["Sale"] = relationship(back_populates="returns")
    lines: Mapped[list["SaleReturnLine"]] = relationship(back_populates="sale_return", order_by="SaleReturnLine.created_at")
    payments: Mapped[list["PaymentTransaction"]] = relationship(back_populates="sale_return", order_by="PaymentTransaction.paid_at")


class SaleReturnLine(Base):
    __tablename__ = "sale_return_lines"
    __table_args__ = (
        UniqueConstraint("sale_line_id", name="uq_sale_return_lines_sale_line"),
        Index("ix_sale_return_lines_return_id", "return_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    return_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sale_returns.id", ondelete="RESTRICT"), nullable=False)
    sale_line_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sale_lines.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=True)
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("storage_locations.id", ondelete="RESTRICT"), nullable=True)
    product_code_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    barcode_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    net_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    weight_unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    settlement_reversal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sale_return: Mapped["SaleReturn"] = relationship(back_populates="lines")
