"""Add idempotency keys to cash drawer movements.

Revision ID: 0029_cash_drawer_idempotency
Revises: 0028_estimate_sale_returns
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029_cash_drawer_idempotency"
down_revision: Union[str, None] = "0028_estimate_sale_returns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cash_drawer_movements",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_cash_drawer_movements_site_idempotency_key",
        "cash_drawer_movements",
        ["site_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_cash_drawer_movements_site_idempotency_key",
        table_name="cash_drawer_movements",
    )
    op.drop_column("cash_drawer_movements", "idempotency_key")
