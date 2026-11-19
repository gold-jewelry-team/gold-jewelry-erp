"""Add company-specific labor dark-code configuration.

Revision ID: 0024_labor_code_settings
Revises: 0023_purchase_labor_cost
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0024_labor_code_settings"
down_revision: Union[str, None] = "0023_purchase_labor_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "labor_code_settings",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prefix", sa.String(length=5), server_default="A", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("company_id"),
    )
    op.create_table(
        "labor_code_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("digit", sa.SmallInteger(), nullable=False),
        sa.Column("code_char", sa.String(length=10), nullable=False),
        sa.CheckConstraint("digit >= 0 AND digit <= 9", name="ck_labor_code_mappings_digit_range"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "digit", name="uq_labor_code_mappings_company_digit"),
    )
    op.create_index("ix_labor_code_mappings_company_id", "labor_code_mappings", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_labor_code_mappings_company_id", table_name="labor_code_mappings")
    op.drop_table("labor_code_mappings")
    op.drop_table("labor_code_settings")
