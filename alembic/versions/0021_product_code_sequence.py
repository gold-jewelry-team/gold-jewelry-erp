"""Add company-wide product code sequences.

Revision ID: 0021_product_code_sequence
Revises: 0020_sales_card_tender
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021_product_code_sequence"
down_revision: Union[str, None] = "0020_sales_card_tender"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_code_sequences",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("next_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("number_width", sa.Integer(), server_default="5", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("company_id"),
        sa.CheckConstraint("next_number >= 1", name="ck_product_code_sequences_next_positive"),
        sa.CheckConstraint("number_width BETWEEN 1 AND 12", name="ck_product_code_sequences_width_range"),
    )
    sequences = sa.table(
        "product_code_sequences",
        sa.column("company_id", sa.Uuid()),
        sa.column("next_number", sa.Integer()),
        sa.column("number_width", sa.Integer()),
    )
    companies = sa.table("companies", sa.column("id", sa.Uuid()))
    op.execute(
        sa.insert(sequences).from_select(
            ["company_id", "next_number", "number_width"],
            sa.select(companies.c.id, sa.literal(1), sa.literal(5)),
        )
    )


def downgrade() -> None:
    op.drop_table("product_code_sequences")
