"""Operating expense records for store operations."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class OperatingExpense(Base):
    __tablename__ = "operating_expenses"
    __table_args__ = (
        UniqueConstraint("site_id", "expense_no", name="uq_operating_expenses_site_expense_no"),
        CheckConstraint("amount > 0", name="ck_operating_expenses_amount_positive"),
        CheckConstraint("currency_code = 'TWD'", name="ck_operating_expenses_currency_twd"),
        CheckConstraint("category_code IN ('RENT','UTILITIES','SALARIES','SUPPLIES','SHIPPING','REPAIR','OTHER')", name="ck_operating_expenses_category"),
        CheckConstraint("status IN ('UNPAID','PAID','VOID')", name="ck_operating_expenses_status"),
        CheckConstraint("payment_method IS NULL OR payment_method IN ('CASH','CARD','TRANSFER','OTHER')", name="ck_operating_expenses_method"),
        CheckConstraint("(status = 'PAID' AND payment_method IS NOT NULL AND paid_at IS NOT NULL) OR (status != 'PAID' AND paid_at IS NULL)", name="ck_operating_expenses_paid_fields"),
        Index("ix_operating_expenses_company_site_date", "company_id", "site_id", "expense_date"),
        Index("ix_operating_expenses_company_site_paid_at", "company_id", "site_id", "paid_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    expense_no: Mapped[str] = mapped_column(String(50), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    payee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="UNPAID", server_default="UNPAID")
    payment_method: Mapped[str | None] = mapped_column(String(12), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    receipt_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
