"""Append-only records of actual customer collections and refunds."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        CheckConstraint("direction IN ('IN', 'OUT')", name="ck_payment_transactions_direction"),
        CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_payment_transactions_method"),
        CheckConstraint("amount > 0", name="ck_payment_transactions_amount_positive"),
        CheckConstraint(
            "(sale_id IS NOT NULL AND sale_return_id IS NULL AND customer_order_id IS NULL) OR "
            "(sale_id IS NULL AND sale_return_id IS NOT NULL AND customer_order_id IS NULL) OR "
            "(sale_id IS NULL AND sale_return_id IS NULL AND customer_order_id IS NOT NULL)",
            name="ck_payment_transactions_exactly_one_source",
        ),
        Index("ix_payment_transactions_company_site_paid_at", "company_id", "site_id", "paid_at"),
        Index("ix_payment_transactions_sale_id", "sale_id"),
        Index("ix_payment_transactions_return_id", "sale_return_id"),
        Index("ix_payment_transactions_customer_order_id", "customer_order_id"),
        Index(
            "uq_payment_transactions_company_idempotency_key",
            "company_id", "idempotency_key", unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=True)
    sale_return_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sale_returns.id", ondelete="RESTRICT"), nullable=True)
    customer_order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("customer_orders.id", ondelete="RESTRICT"), nullable=True)
    customer_order: Mapped["CustomerOrder | None"] = relationship(back_populates="payments")
    sale_return: Mapped["SaleReturn | None"] = relationship(back_populates="payments")
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(12), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
