"""Add gold price history.

Revision ID: 0002_gold_prices
Revises: 0001_core
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_gold_prices"
down_revision: Union[str, None] = "0001_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gold_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("price_type", sa.String(length=10), nullable=False),
        sa.Column("price_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency_code", sa.String(length=3), server_default="TWD", nullable=False),
        sa.Column("unit_code", sa.String(length=20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), server_default="MANUAL", nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("price_type IN ('BUY', 'SELL')", name="ck_gold_prices_price_type"),
        sa.CheckConstraint("price_value > 0", name="ck_gold_prices_price_value_positive"),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_gold_prices_currency_code_length"),
        sa.CheckConstraint("length(unit_code) BETWEEN 1 AND 20", name="ck_gold_prices_unit_code_length"),
        sa.CheckConstraint("source IN ('MANUAL', 'IMPORT', 'SYSTEM')", name="ck_gold_prices_source"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gold_prices_company_id", "gold_prices", ["company_id"], unique=False)
    op.create_index("ix_gold_prices_site_id", "gold_prices", ["site_id"], unique=False)
    op.create_index(
        "ix_gold_prices_scope_type_effective",
        "gold_prices",
        ["company_id", "site_id", "price_type", "effective_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_gold_prices_scope_type_effective", table_name="gold_prices")
    op.drop_index("ix_gold_prices_site_id", table_name="gold_prices")
    op.drop_index("ix_gold_prices_company_id", table_name="gold_prices")
    op.drop_table("gold_prices")
