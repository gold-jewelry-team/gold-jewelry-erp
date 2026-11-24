"""Add idempotency keys to bank operations.

Revision ID: 0032_bank_operation_idempotency
Revises: 0031_bank_transfer_source_links
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032_bank_operation_idempotency"
down_revision: Union[str, None] = "0031_bank_transfer_source_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bank_transactions",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_bank_transactions_company_idempotency_key",
        "bank_transactions",
        ["company_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_bank_transactions_company_idempotency_key",
        table_name="bank_transactions",
    )
    op.drop_column("bank_transactions", "idempotency_key")
