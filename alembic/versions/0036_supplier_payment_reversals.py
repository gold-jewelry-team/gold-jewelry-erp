"""Add append-only supplier-payment reversals.

Revision ID: 0036_supplier_payment_reversals
Revises: 0035_company_role_permissions
Create Date: 2026-11-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0036_supplier_payment_reversals"
down_revision: Union[str, None] = "0035_company_role_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplier_payment_reversals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("reversal_no", sa.String(length=50), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), server_default="TWD", nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("total_amount > 0", name="ck_supplier_payment_reversals_total_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_id"], ["supplier_payments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "reversal_no", name="uq_supplier_payment_reversals_site_no"),
    )
    op.create_index(
        "ix_supplier_payment_reversals_company_site_reversed_at",
        "supplier_payment_reversals",
        ["company_id", "site_id", "reversed_at"],
    )
    op.create_table(
        "supplier_payment_reversal_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reversal_id", sa.Uuid(), nullable=False),
        sa.Column("payment_allocation_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_supplier_payment_reversal_allocations_amount_positive"),
        sa.ForeignKeyConstraint(["reversal_id"], ["supplier_payment_reversals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_allocation_id"], ["supplier_payment_allocations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reversal_id",
            "payment_allocation_id",
            name="uq_supplier_payment_reversal_allocation_original",
        ),
    )
    op.create_index(
        "ix_supplier_payment_reversal_allocations_original",
        "supplier_payment_reversal_allocations",
        ["payment_allocation_id"],
    )
    op.add_column(
        "daily_closings",
        sa.Column("supplier_payment_reversed_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "daily_closing_payment_summaries",
        sa.Column("supplier_payment_reversed_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("daily_closing_payment_summaries", "supplier_payment_reversed_amount")
    op.drop_column("daily_closings", "supplier_payment_reversed_amount")
    op.drop_index(
        "ix_supplier_payment_reversal_allocations_original",
        table_name="supplier_payment_reversal_allocations",
    )
    op.drop_table("supplier_payment_reversal_allocations")
    op.drop_index(
        "ix_supplier_payment_reversals_company_site_reversed_at",
        table_name="supplier_payment_reversals",
    )
    op.drop_table("supplier_payment_reversals")
