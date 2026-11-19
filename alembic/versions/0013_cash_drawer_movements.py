"""Add cash drawer movements and closing cash adjustments.
Revision ID: 0013_cash_drawer_movements
Revises: 0012_daily_cash_counts
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0013_cash_drawer_movements"
down_revision: Union[str,None] = "0012_daily_cash_counts"
branch_labels: Union[str,Sequence[str],None] = None
depends_on: Union[str,Sequence[str],None] = None

def upgrade() -> None:
    op.create_table(
        "cash_drawer_movements",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("site_id",sa.Uuid(),nullable=False),
        sa.Column("movement_type",sa.String(20),nullable=False),
        sa.Column("direction",sa.String(3),nullable=False),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),
        sa.Column("currency_code",sa.String(3),server_default="TWD",nullable=False),
        sa.Column("reference_no",sa.String(100),nullable=True),
        sa.Column("description",sa.String(200),nullable=False),
        sa.Column("created_by_name",sa.String(120),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("note",sa.String(500),nullable=True),
        sa.CheckConstraint("movement_type IN ('BANK_DEPOSIT','BANK_WITHDRAWAL','FLOAT_INCREASE','FLOAT_DECREASE','OTHER_IN','OTHER_OUT')",name="ck_cash_drawer_movements_type"),
        sa.CheckConstraint("direction IN ('IN','OUT')",name="ck_cash_drawer_movements_direction"),
        sa.CheckConstraint("(movement_type IN ('BANK_WITHDRAWAL','FLOAT_INCREASE','OTHER_IN') AND direction = 'IN') OR (movement_type IN ('BANK_DEPOSIT','FLOAT_DECREASE','OTHER_OUT') AND direction = 'OUT')",name="ck_cash_drawer_movements_type_direction"),
        sa.CheckConstraint("amount > 0",name="ck_cash_drawer_movements_amount_positive"),
        sa.CheckConstraint("currency_code = 'TWD'",name="ck_cash_drawer_movements_currency_twd"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"],["sites.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cash_drawer_movements_company_site_created_at","cash_drawer_movements",["company_id","site_id","created_at"])
    for table in ("daily_closings","daily_closing_payment_summaries"):
        op.add_column(table,sa.Column("cash_drawer_in_amount",sa.Numeric(18,2),server_default="0",nullable=False))
        op.add_column(table,sa.Column("cash_drawer_out_amount",sa.Numeric(18,2),server_default="0",nullable=False))

def downgrade() -> None:
    for table in ("daily_closing_payment_summaries","daily_closings"):
        op.drop_column(table,"cash_drawer_out_amount")
        op.drop_column(table,"cash_drawer_in_amount")
    op.drop_index("ix_cash_drawer_movements_company_site_created_at",table_name="cash_drawer_movements")
    op.drop_table("cash_drawer_movements")
