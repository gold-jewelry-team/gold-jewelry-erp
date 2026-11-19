"""Bank accounts and immutable bank transaction ledger."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        CheckConstraint("currency_code = 'TWD'", name="ck_bank_accounts_currency_twd"),
        CheckConstraint("opening_balance >= 0", name="ck_bank_accounts_opening_balance_nonnegative"),
        Index("ix_bank_accounts_company_active", "company_id", "is_active"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False, default=Decimal("0"), server_default="0")
    opening_balance_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        CheckConstraint("direction IN ('IN','OUT')", name="ck_bank_transactions_direction"),
        CheckConstraint("transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT')", name="ck_bank_transactions_type"),
        CheckConstraint("amount > 0", name="ck_bank_transactions_amount_positive"),
        CheckConstraint("currency_code = 'TWD'", name="ck_bank_transactions_currency_twd"),
        CheckConstraint("(transaction_type IN ('CASH_DEPOSIT','TRANSFER_IN') AND direction = 'IN') OR (transaction_type IN ('CASH_WITHDRAWAL','TRANSFER_OUT') AND direction = 'OUT')", name="ck_bank_transactions_type_direction"),
        Index("ix_bank_transactions_account_occurred", "bank_account_id", "occurred_at"),
        Index("ix_bank_transactions_company_site_occurred", "company_id", "site_id", "occurred_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True)
    transfer_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
