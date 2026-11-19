"""Add supplier bills, payments, and allocations.

Revision ID: 0010_supplier_payables
Revises: 0009_payment_transactions
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_supplier_payables"
down_revision: Union[str, None] = "0009_payment_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplier_bills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_id", sa.Uuid(), nullable=True),
        sa.Column("bill_no", sa.String(length=50), nullable=False),
        sa.Column("bill_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency_code", sa.String(length=3), server_default="TWD", nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("total_amount > 0", name="ck_supplier_bills_total_positive"),
        sa.CheckConstraint("status IN ('OPEN', 'PARTIALLY_PAID', 'PAID', 'VOID')", name="ck_supplier_bills_status"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "supplier_id", "bill_no", name="uq_supplier_bills_supplier_bill_no"),
    )
    op.create_index("ix_supplier_bills_company_site_due", "supplier_bills", ["company_id", "site_id", "due_date"])

    op.create_table(
        "supplier_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("payment_no", sa.String(length=50), nullable=False),
        sa.Column("payment_method", sa.String(length=12), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), server_default="TWD", nullable=False),
        sa.Column("reference_no", sa.String(length=100), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("total_amount > 0", name="ck_supplier_payments_total_positive"),
        sa.CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_supplier_payments_method"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "payment_no", name="uq_supplier_payments_site_payment_no"),
    )
    op.create_index("ix_supplier_payments_company_site_paid_at", "supplier_payments", ["company_id", "site_id", "paid_at"])

    op.create_table(
        "supplier_payment_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("bill_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_supplier_payment_allocations_amount_positive"),
        sa.ForeignKeyConstraint(["payment_id"], ["supplier_payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bill_id"], ["supplier_bills.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "bill_id", name="uq_supplier_payment_allocation_payment_bill"),
    )
    op.create_index("ix_supplier_payment_allocations_bill_id", "supplier_payment_allocations", ["bill_id"])

    op.add_column(
        "daily_closings",
        sa.Column("supplier_paid_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "daily_closing_payment_summaries",
        sa.Column("supplier_paid_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("daily_closing_payment_summaries", "supplier_paid_amount")
    op.drop_column("daily_closings", "supplier_paid_amount")
    op.drop_index("ix_supplier_payment_allocations_bill_id", table_name="supplier_payment_allocations")
    op.drop_table("supplier_payment_allocations")
    op.drop_index("ix_supplier_payments_company_site_paid_at", table_name="supplier_payments")
    op.drop_table("supplier_payments")
    op.drop_index("ix_supplier_bills_company_site_due", table_name="supplier_bills")
    op.drop_table("supplier_bills")
