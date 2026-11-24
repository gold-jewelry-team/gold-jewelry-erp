"""Bank accounts and immutable bank transaction ledger."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Uuid, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        CheckConstraint("currency_code = 'TWD'", name="ck_bank_accounts_currency_twd"),
        CheckConstraint("opening_balance >= 0", name="ck_bank_accounts_opening_balance_nonnegative"),
        UniqueConstraint("id", "company_id", name="uq_bank_accounts_id_company"),
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
        CheckConstraint("transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT','BANK_FEE','INTEREST_IN','OTHER_ADJUSTMENT')", name="ck_bank_transactions_type"),
        CheckConstraint("amount > 0", name="ck_bank_transactions_amount_positive"),
        CheckConstraint("currency_code = 'TWD'", name="ck_bank_transactions_currency_twd"),
        CheckConstraint("(transaction_type IN ('CASH_DEPOSIT','TRANSFER_IN','INTEREST_IN') AND direction = 'IN') OR (transaction_type IN ('CASH_WITHDRAWAL','TRANSFER_OUT','BANK_FEE') AND direction = 'OUT') OR transaction_type = 'OTHER_ADJUSTMENT'", name="ck_bank_transactions_type_direction"),
        Index("ix_bank_transactions_account_occurred", "bank_account_id", "occurred_at"),
        Index("ix_bank_transactions_company_site_occurred", "company_id", "site_id", "occurred_at"),
        Index("ix_bank_transactions_statement_line", "statement_line_id", unique=True),
        CheckConstraint(
            "(source_type IS NULL AND source_id IS NULL) OR "
            "(source_type IS NOT NULL AND source_id IS NOT NULL)",
            name="ck_bank_transactions_source_pair",
        ),
        Index(
            "uq_bank_transactions_company_source",
            "company_id", "source_type", "source_id", unique=True,
            postgresql_where=text("source_type IS NOT NULL AND source_id IS NOT NULL"),
            sqlite_where=text("source_type IS NOT NULL AND source_id IS NOT NULL"),
        ),
        UniqueConstraint("id", "company_id", "bank_account_id", name="uq_bank_transactions_id_scope"),
        ForeignKeyConstraint(["bank_account_id", "company_id"], ["bank_accounts.id", "bank_accounts.company_id"], ondelete="RESTRICT", name="fk_bank_transactions_account_company"),
        ForeignKeyConstraint(["statement_line_id", "company_id", "bank_account_id"], ["bank_statement_lines.id", "bank_statement_lines.company_id", "bank_statement_lines.bank_account_id"], ondelete="RESTRICT", name="fk_bank_transactions_statement_line_scope"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True)
    statement_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_statement_lines.id", ondelete="RESTRICT"), nullable=True)
    transfer_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
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
