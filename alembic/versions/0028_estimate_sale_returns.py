"""Allow returns for non-inventory temporary estimate sale lines.

Revision ID: 0028_estimate_sale_returns
Revises: 0027_customer_orders_deposits
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0028_estimate_sale_returns"
down_revision: Union[str, None] = "0027_customer_orders_deposits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("sale_return_lines", "product_id", nullable=True)
    op.alter_column("sale_return_lines", "source_location_id", nullable=True)


def downgrade() -> None:
    op.alter_column("sale_return_lines", "source_location_id", nullable=False)
    op.alter_column("sale_return_lines", "product_id", nullable=False)
