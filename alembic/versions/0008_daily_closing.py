"""Create immutable daily closing snapshots.

Revision ID: 0008_daily_closing
Revises: 0007_sales_returns
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_daily_closing"
down_revision: Union[str, None] = "0007_sales_returns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_closings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), server_default="TWD", nullable=False),
        sa.Column("sales_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returns_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_sales_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("return_reversal_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_sales_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("closed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.CheckConstraint("sales_count >= 0 AND returns_count >= 0", name="ck_daily_closings_counts_nonnegative"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "business_date", name="uq_daily_closings_site_business_date"),
    )
    op.create_index(
        "ix_daily_closings_company_site_date",
        "daily_closings",
        ["company_id", "site_id", "business_date"],
    )

    op.create_table(
        "daily_closing_payment_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("closing_id", sa.Uuid(), nullable=False),
        sa.Column("payment_method", sa.String(length=12), nullable=False),
        sa.Column("sales_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returns_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_sales_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("return_reversal_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_sales_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.CheckConstraint("sales_count >= 0 AND returns_count >= 0", name="ck_daily_closing_payment_counts_nonnegative"),
        sa.CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_daily_closing_payment_method"),
        sa.ForeignKeyConstraint(["closing_id"], ["daily_closings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("closing_id", "payment_method", name="uq_daily_closing_payment_method"),
    )
    op.create_index(
        "ix_daily_closing_payment_summaries_closing_id",
        "daily_closing_payment_summaries",
        ["closing_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_closing_payment_summaries_closing_id", table_name="daily_closing_payment_summaries")
    op.drop_table("daily_closing_payment_summaries")
    op.drop_index("ix_daily_closings_company_site_date", table_name="daily_closings")
    op.drop_table("daily_closings")
