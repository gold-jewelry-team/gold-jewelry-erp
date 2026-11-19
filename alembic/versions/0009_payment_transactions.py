"""Add actual payment transactions and daily closing cash-flow totals.

Revision ID: 0009_payment_transactions
Revises: 0008_daily_closing
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_payment_transactions"
down_revision: Union[str, None] = "0008_daily_closing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("sale_id", sa.Uuid(), nullable=True),
        sa.Column("sale_return_id", sa.Uuid(), nullable=True),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("payment_method", sa.String(length=12), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), server_default="TWD", nullable=False),
        sa.Column("reference_no", sa.String(length=100), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("direction IN ('IN', 'OUT')", name="ck_payment_transactions_direction"),
        sa.CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_payment_transactions_method"),
        sa.CheckConstraint("amount > 0", name="ck_payment_transactions_amount_positive"),
        sa.CheckConstraint(
            "(sale_id IS NOT NULL AND sale_return_id IS NULL) OR "
            "(sale_id IS NULL AND sale_return_id IS NOT NULL)",
            name="ck_payment_transactions_exactly_one_source",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sale_return_id"], ["sale_returns.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_transactions_company_site_paid_at", "payment_transactions", ["company_id", "site_id", "paid_at"])
    op.create_index("ix_payment_transactions_sale_id", "payment_transactions", ["sale_id"])
    op.create_index("ix_payment_transactions_return_id", "payment_transactions", ["sale_return_id"])

    for table in ("daily_closings", "daily_closing_payment_summaries"):
        op.add_column(table, sa.Column("collected_amount", sa.Numeric(18, 2), server_default="0", nullable=False))
        op.add_column(table, sa.Column("refunded_amount", sa.Numeric(18, 2), server_default="0", nullable=False))
        op.add_column(table, sa.Column("net_cash_flow", sa.Numeric(18, 2), server_default="0", nullable=False))


def downgrade() -> None:
    for table in ("daily_closing_payment_summaries", "daily_closings"):
        op.drop_column(table, "net_cash_flow")
        op.drop_column(table, "refunded_amount")
        op.drop_column(table, "collected_amount")
    op.drop_index("ix_payment_transactions_return_id", table_name="payment_transactions")
    op.drop_index("ix_payment_transactions_sale_id", table_name="payment_transactions")
    op.drop_index("ix_payment_transactions_company_site_paid_at", table_name="payment_transactions")
    op.drop_table("payment_transactions")
