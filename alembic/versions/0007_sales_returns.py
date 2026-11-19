"""Create sales return records and item-level return ledger links.

Revision ID: 0007_sales_returns
Revises: 0006_sales_inventory_links
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_sales_returns"
down_revision: Union[str, None] = "0006_sales_inventory_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sale_returns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("sale_id", sa.Uuid(), nullable=False),
        sa.Column("return_no", sa.String(length=40), nullable=False),
        sa.Column("settlement_reversal_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), server_default="TWD", nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "return_no", name="uq_sale_returns_site_return_no"),
    )
    op.create_index(
        "ix_sale_returns_company_site_created",
        "sale_returns",
        ["company_id", "site_id", "created_at"],
    )

    op.create_table(
        "sale_return_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("return_id", sa.Uuid(), nullable=False),
        sa.Column("sale_line_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("source_location_id", sa.Uuid(), nullable=False),
        sa.Column("product_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column("barcode_snapshot", sa.String(length=100), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("net_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("weight_unit_code", sa.String(length=20), nullable=False),
        sa.Column("refund_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["return_id"], ["sale_returns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sale_line_id"], ["sale_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_location_id"], ["storage_locations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_line_id", name="uq_sale_return_lines_sale_line"),
    )
    op.create_index("ix_sale_return_lines_return_id", "sale_return_lines", ["return_id"])


def downgrade() -> None:
    op.drop_index("ix_sale_return_lines_return_id", table_name="sale_return_lines")
    op.drop_table("sale_return_lines")
    op.drop_index("ix_sale_returns_company_site_created", table_name="sale_returns")
    op.drop_table("sale_returns")
