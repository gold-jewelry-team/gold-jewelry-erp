"""Append-only physical cash drawer movements."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class CashDrawerMovement(Base):
    __tablename__ = "cash_drawer_movements"
    __table_args__ = (
        CheckConstraint("movement_type IN ('BANK_DEPOSIT','BANK_WITHDRAWAL','FLOAT_INCREASE','FLOAT_DECREASE','OTHER_IN','OTHER_OUT')", name="ck_cash_drawer_movements_type"),
        CheckConstraint("direction IN ('IN','OUT')", name="ck_cash_drawer_movements_direction"),
        CheckConstraint("(movement_type IN ('BANK_WITHDRAWAL','FLOAT_INCREASE','OTHER_IN') AND direction = 'IN') OR (movement_type IN ('BANK_DEPOSIT','FLOAT_DECREASE','OTHER_OUT') AND direction = 'OUT')", name="ck_cash_drawer_movements_type_direction"),
        CheckConstraint("amount > 0", name="ck_cash_drawer_movements_amount_positive"),
        CheckConstraint("currency_code = 'TWD'", name="ck_cash_drawer_movements_currency_twd"),
        Index("ix_cash_drawer_movements_company_site_created_at", "company_id", "site_id", "created_at"),
    )
    bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=True, unique=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
