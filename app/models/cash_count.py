"""Immutable daily cash count with a separately recorded review."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class DailyCashCount(Base):
    __tablename__ = "daily_cash_counts"
    __table_args__ = (
        UniqueConstraint("closing_id", name="uq_daily_cash_counts_closing_id"),
        CheckConstraint("opening_cash_float >= 0", name="ck_daily_cash_counts_opening_nonnegative"),
        CheckConstraint("expected_cash_amount >= 0", name="ck_daily_cash_counts_expected_nonnegative"),
        CheckConstraint("counted_cash_amount >= 0", name="ck_daily_cash_counts_counted_nonnegative"),
        CheckConstraint("cash_variance = counted_cash_amount - expected_cash_amount", name="ck_daily_cash_counts_variance_matches"),
        CheckConstraint("(reviewed_by_name IS NULL AND reviewed_at IS NULL) OR (reviewed_by_name IS NOT NULL AND reviewed_at IS NOT NULL)", name="ck_daily_cash_counts_review_fields"),
        Index("ix_daily_cash_counts_company_site_counted_at", "company_id", "site_id", "counted_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    closing_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_closings.id", ondelete="RESTRICT"), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    opening_cash_float: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    expected_cash_amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    counted_cash_amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    cash_variance: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    counted_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    count_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
