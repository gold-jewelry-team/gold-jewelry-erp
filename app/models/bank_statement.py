"""Imported bank statement batches and immutable statement lines."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class BankStatementImport(Base):
    __tablename__ = "bank_statement_imports"
    __table_args__ = (
        CheckConstraint("status IN ('IMPORTED','REVIEWED')", name="ck_bank_statement_imports_status"),
        Index("ix_bank_statement_imports_account_created", "bank_account_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    row_count: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IMPORTED", server_default="IMPORTED")
    imported_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class BankStatementLine(Base):
    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        CheckConstraint("direction IN ('IN','OUT')", name="ck_bank_statement_lines_direction"),
        CheckConstraint("amount > 0", name="ck_bank_statement_lines_amount_positive"),
        CheckConstraint("status IN ('UNMATCHED','MATCHED','DUPLICATE','IGNORED')", name="ck_bank_statement_lines_status"),
        Index("ix_bank_statement_lines_import_status", "import_id", "status"),
        Index("ix_bank_statement_lines_account_date_amount", "bank_account_id", "transaction_date", "amount"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_statement_imports.id", ondelete="RESTRICT"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False)
    transaction_date: Mapped[date] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18,2), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNMATCHED", server_default="UNMATCHED")
    matched_bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=True, unique=True)
    duplicate_of_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("bank_statement_lines.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
