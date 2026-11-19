"""Add sales and per-line pricing snapshots.

Revision ID: 0003_sales_snapshots
Revises: 0002_gold_prices
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_sales_snapshots"
down_revision: Union[str, None] = "0002_gold_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("sale_no", sa.String(40), nullable=False),
        sa.Column("status", sa.String(12), server_default="DRAFT", nullable=False),
        sa.Column("payment_method", sa.String(12), server_default="CASH", nullable=False),
        sa.Column("currency_code", sa.String(3), server_default="TWD", nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("card_fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("final_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'COMPLETED', 'VOID')", name="ck_sales_status"),
        sa.CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_sales_payment_method"),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_sales_currency_code_length"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "sale_no", name="uq_sales_site_sale_no"),
    )
    op.create_index("ix_sales_company_id", "sales", ["company_id"])
    op.create_index("ix_sales_site_id", "sales", ["site_id"])
    op.create_index("ix_sales_company_site_created", "sales", ["company_id", "site_id", "created_at"])

    op.create_table(
        "sale_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sale_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_code_snapshot", sa.String(50), nullable=True),
        sa.Column("barcode_snapshot", sa.String(100), nullable=True),
        sa.Column("product_name_snapshot", sa.String(200), nullable=False),
        sa.Column("gross_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("net_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("weight_unit_code", sa.String(20), nullable=False),
        sa.Column("labor_fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("sell_gold_price_id", sa.Uuid(), nullable=True),
        sa.Column("sell_gold_price_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("sell_gold_price_unit_code", sa.String(20), nullable=False),
        sa.Column("buy_gold_price_id", sa.Uuid(), nullable=True),
        sa.Column("buy_gold_price_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("buy_gold_price_unit_code", sa.String(20), nullable=False),
        sa.Column("price_currency_code", sa.String(3), server_default="TWD", nullable=False),
        sa.Column("price_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trade_in_source", sa.String(10), nullable=True),
        sa.Column("old_gold_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("trade_in_ratio", sa.Numeric(8, 6), nullable=True),
        sa.Column("adjusted_old_gold_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("pricing_rule_version", sa.String(40), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("card_fee", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("final_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("gross_weight >= 0", name="ck_sale_lines_gross_weight_nonnegative"),
        sa.CheckConstraint("net_weight >= 0", name="ck_sale_lines_net_weight_nonnegative"),
        sa.CheckConstraint("labor_fee >= 0", name="ck_sale_lines_labor_fee_nonnegative"),
        sa.CheckConstraint("trade_in_source IS NULL OR trade_in_source IN ('LOCAL', 'EXTERNAL')", name="ck_sale_lines_trade_in_source"),
        sa.CheckConstraint("trade_in_ratio IS NULL OR (trade_in_ratio > 0 AND trade_in_ratio <= 1)", name="ck_sale_lines_trade_in_ratio"),
        sa.CheckConstraint("length(price_currency_code) = 3", name="ck_sale_lines_currency_code_length"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sell_gold_price_id"], ["gold_prices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["buy_gold_price_id"], ["gold_prices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_id", "line_no", name="uq_sale_lines_sale_line_no"),
    )
    op.create_index("ix_sale_lines_sale_id", "sale_lines", ["sale_id"])


def downgrade() -> None:
    op.drop_index("ix_sale_lines_sale_id", table_name="sale_lines")
    op.drop_table("sale_lines")
    op.drop_index("ix_sales_company_site_created", table_name="sales")
    op.drop_index("ix_sales_site_id", table_name="sales")
    op.drop_index("ix_sales_company_id", table_name="sales")
    op.drop_table("sales")
