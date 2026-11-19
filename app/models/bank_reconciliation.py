"""Append-only snapshots of bank statement reconciliation attempts."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class BankReconciliationSnapshot(Base):
    __tablename__ = "bank_reconciliation_snapshots"
    __table_args__ = (
        CheckConstraint("period_end >= period_start", name="ck_bank_reconciliation_period_order"),
        CheckConstraint("status IN ('RECONCILED','NEEDS_REVIEW')", name="ck_bank_reconciliation_status"),
        CheckConstraint("statement_line_count >= 0 AND matched_line_count >= 0 AND unmatched_line_count >= 0 AND duplicate_line_count >= 0 AND ignored_line_count >= 0 AND unmatched_ledger_count >= 0", name="ck_bank_reconciliation_counts_nonnegative"),
        Index("ix_bank_reconciliation_account_period", "bank_account_id", "period_start", "period_end"),
        ForeignKeyConstraint(["bank_account_id", "company_id"], ["bank_accounts.id", "bank_accounts.company_id"], ondelete="RESTRICT", name="fk_bank_reconciliation_account_company"),
        ForeignKeyConstraint(["import_id", "company_id", "bank_account_id"], ["bank_statement_imports.id", "bank_statement_imports.company_id", "bank_statement_imports.bank_account_id"], ondelete="RESTRICT", name="fk_bank_reconciliation_import_scope"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False)
    import_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_statement_imports.id", ondelete="RESTRICT"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    statement_opening_balance: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    statement_closing_balance: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    statement_net_movement: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    ledger_net_movement: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    balance_difference: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    net_difference: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    statement_line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unmatched_line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ignored_line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unmatched_ledger_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reconciled_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
