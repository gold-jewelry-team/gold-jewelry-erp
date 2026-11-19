"""Immutable daily closing snapshots and payment-method summaries."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DailyClosing(Base):
    __tablename__ = "daily_closings"
    __table_args__ = (
        CheckConstraint("sales_count >= 0 AND returns_count >= 0", name="ck_daily_closings_counts_nonnegative"),
        Index("ix_daily_closings_company_site_date", "company_id", "site_id", "business_date"),
        UniqueConstraint("site_id", "business_date", name="uq_daily_closings_site_business_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    sales_count: Mapped[int] = mapped_column(nullable=False, default=0)
    returns_count: Mapped[int] = mapped_column(nullable=False, default=0)
    gross_sales_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    return_reversal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    net_sales_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    collected_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    net_cash_flow: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_summaries: Mapped[list["DailyClosingPaymentSummary"]] = relationship(
        back_populates="closing", cascade="all, delete-orphan", order_by="DailyClosingPaymentSummary.payment_method"
    )


class DailyClosingPaymentSummary(Base):
    __tablename__ = "daily_closing_payment_summaries"
    __table_args__ = (
        CheckConstraint("sales_count >= 0 AND returns_count >= 0", name="ck_daily_closing_payment_counts_nonnegative"),
        UniqueConstraint("closing_id", "payment_method", name="uq_daily_closing_payment_method"),
        CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_daily_closing_payment_method"),
        Index("ix_daily_closing_payment_summaries_closing_id", "closing_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    closing_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_closings.id", ondelete="RESTRICT"), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(12), nullable=False)
    sales_count: Mapped[int] = mapped_column(nullable=False, default=0)
    returns_count: Mapped[int] = mapped_column(nullable=False, default=0)
    gross_sales_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    return_reversal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    net_sales_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    collected_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    net_cash_flow: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    closing: Mapped["DailyClosing"] = relationship(back_populates="payment_summaries")
