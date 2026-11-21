"""Customer special orders; receipts use the shared payment ledger and never reserve or deduct stock."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CustomerOrder(Base):
    __tablename__ = "customer_orders"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING_DEPOSIT', 'IN_PROGRESS', 'ARRIVED', 'READY', 'COMPLETED', 'CANCELLED')", name="ck_customer_orders_status"),
        CheckConstraint("total_amount >= 0 AND deposit_amount >= 0 AND deposit_amount <= total_amount", name="ck_customer_orders_amounts"),
        Index("ix_customer_orders_company_site_created", "company_id", "site_id", "created_at"),
        UniqueConstraint("site_id", "order_no", name="uq_customer_orders_site_order_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    order_no: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING_DEPOSIT", server_default="PENDING_DEPOSIT")
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_delivery_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    payments: Mapped[list["PaymentTransaction"]] = relationship(back_populates="customer_order", order_by="PaymentTransaction.paid_at")
