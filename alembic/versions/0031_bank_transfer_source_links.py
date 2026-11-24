"""Add source links for bank ledger transfer payments.

Revision ID: 0031_bank_transfer_source_links
Revises: 0030_payment_idempotency
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031_bank_transfer_source_links"
down_revision: Union[str, None] = "0030_payment_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bank_transactions",
        sa.Column("source_type", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "bank_transactions",
        sa.Column("source_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        "ck_bank_transactions_source_pair",
        "bank_transactions",
        "(source_type IS NULL AND source_id IS NULL) OR "
        "(source_type IS NOT NULL AND source_id IS NOT NULL)",
    )
    op.create_index(
        "uq_bank_transactions_company_source",
        "bank_transactions",
        ["company_id", "source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_type IS NOT NULL AND source_id IS NOT NULL"),
        sqlite_where=sa.text("source_type IS NOT NULL AND source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_bank_transactions_company_source",
        table_name="bank_transactions",
    )
    op.drop_constraint(
        "ck_bank_transactions_source_pair",
        "bank_transactions",
        type_="check",
    )
    op.drop_column("bank_transactions", "source_id")
    op.drop_column("bank_transactions", "source_type")
