"""Add idempotency keys to sale and return payment transactions.

Revision ID: 0030_payment_idempotency
Revises: 0029_cash_drawer_idempotency
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030_payment_idempotency"
down_revision: Union[str, None] = "0029_cash_drawer_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_payment_transactions_company_idempotency_key",
        "payment_transactions",
        ["company_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_payment_transactions_company_idempotency_key",
        table_name="payment_transactions",
    )
    op.drop_column("payment_transactions", "idempotency_key")
