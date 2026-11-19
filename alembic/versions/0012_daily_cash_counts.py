"""Add daily cash count and review records.
Revision ID: 0012_daily_cash_counts
Revises: 0011_operating_expenses
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0012_daily_cash_counts"
down_revision: Union[str,None] = "0011_operating_expenses"
branch_labels: Union[str,Sequence[str],None] = None
depends_on: Union[str,Sequence[str],None] = None

def upgrade() -> None:
    op.create_table(
        "daily_cash_counts",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("site_id",sa.Uuid(),nullable=False),
        sa.Column("closing_id",sa.Uuid(),nullable=False),
        sa.Column("currency_code",sa.String(3),server_default="TWD",nullable=False),
        sa.Column("opening_cash_float",sa.Numeric(18,2),nullable=False),
        sa.Column("expected_cash_amount",sa.Numeric(18,2),nullable=False),
        sa.Column("counted_cash_amount",sa.Numeric(18,2),nullable=False),
        sa.Column("cash_variance",sa.Numeric(18,2),nullable=False),
        sa.Column("counted_by_name",sa.String(120),nullable=False),
        sa.Column("counted_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("count_note",sa.String(500),nullable=True),
        sa.Column("reviewed_by_name",sa.String(120),nullable=True),
        sa.Column("reviewed_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("review_note",sa.String(500),nullable=True),
        sa.CheckConstraint("opening_cash_float >= 0",name="ck_daily_cash_counts_opening_nonnegative"),
        sa.CheckConstraint("expected_cash_amount >= 0",name="ck_daily_cash_counts_expected_nonnegative"),
        sa.CheckConstraint("counted_cash_amount >= 0",name="ck_daily_cash_counts_counted_nonnegative"),
        sa.CheckConstraint("cash_variance = counted_cash_amount - expected_cash_amount",name="ck_daily_cash_counts_variance_matches"),
        sa.CheckConstraint("(reviewed_by_name IS NULL AND reviewed_at IS NULL) OR (reviewed_by_name IS NOT NULL AND reviewed_at IS NOT NULL)",name="ck_daily_cash_counts_review_fields"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"],["sites.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["closing_id"],["daily_closings.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("closing_id",name="uq_daily_cash_counts_closing_id"),
    )
    op.create_index("ix_daily_cash_counts_company_site_counted_at","daily_cash_counts",["company_id","site_id","counted_at"])

def downgrade() -> None:
    op.drop_index("ix_daily_cash_counts_company_site_counted_at",table_name="daily_cash_counts")
    op.drop_table("daily_cash_counts")
