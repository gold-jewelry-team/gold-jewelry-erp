"""Add separately tracked purchase labor cost.

Revision ID: 0023_purchase_labor_cost
Revises: 0022_product_label_details
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023_purchase_labor_cost"
down_revision: Union[str, None] = "0022_product_label_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_lines",
        sa.Column("cost_labor_fee", sa.Numeric(18, 2), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_purchase_lines_cost_labor_fee_nonnegative",
        "purchase_lines",
        "cost_labor_fee >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_purchase_lines_cost_labor_fee_nonnegative", "purchase_lines", type_="check")
    op.drop_column("purchase_lines", "cost_labor_fee")
