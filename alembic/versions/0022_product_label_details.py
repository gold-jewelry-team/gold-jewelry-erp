"""Add product chain length and style code for printable labels.

Revision ID: 0022_product_label_details
Revises: 0021_product_code_sequence
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022_product_label_details"
down_revision: Union[str, None] = "0021_product_code_sequence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("chain_length", sa.String(length=40), nullable=True))
    op.add_column("products", sa.Column("style_code", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "style_code")
    op.drop_column("products", "chain_length")
