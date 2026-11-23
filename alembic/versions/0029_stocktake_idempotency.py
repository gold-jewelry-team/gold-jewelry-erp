"""Add idempotency keys for retry-safe stocktake adjustments.

Revision ID: 0029_stocktake_idempotency
Revises: 0028_estimate_sale_returns
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029_stocktake_idempotency"
down_revision: Union[str, None] = "0028_estimate_sale_returns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_movements",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_inventory_movements_company_idempotency_key",
        "inventory_movements",
        ["company_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_inventory_movements_company_idempotency_key",
        table_name="inventory_movements",
    )
    op.drop_column("inventory_movements", "idempotency_key")
