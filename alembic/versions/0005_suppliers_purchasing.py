"""Add suppliers, purchase orders and receiving quantities.

Revision ID: 0005_suppliers_purchasing
Revises: 0004_products_inventory
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_suppliers_purchasing"
down_revision: Union[str, None] = "0004_products_inventory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("tax_id", sa.String(20), nullable=True),
        sa.Column("contact_name", sa.String(80), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_suppliers_company_code"),
    )
    op.create_index("ix_suppliers_company_id", "suppliers", ["company_id"])

    op.create_table(
        "purchases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_no", sa.String(50), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(24), server_default="DRAFT", nullable=False),
        sa.Column("currency_code", sa.String(3), server_default="TWD", nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'ORDERED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'CANCELLED')", name="ck_purchases_status"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "purchase_no", name="uq_purchases_company_no"),
    )
    op.create_index("ix_purchases_company_id", "purchases", ["company_id"])
    op.create_index("ix_purchases_site_id", "purchases", ["site_id"])
    op.create_index("ix_purchases_supplier_id", "purchases", ["supplier_id"])

    op.create_table(
        "purchase_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("weight", sa.Numeric(18, 4), nullable=True),
        sa.Column("weight_unit_code", sa.String(20), nullable=True),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_lines_quantity_positive"),
        sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= quantity", name="ck_purchase_lines_received_quantity"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_purchase_lines_unit_cost_nonnegative"),
        sa.CheckConstraint("weight IS NULL OR weight >= 0", name="ck_purchase_lines_weight_nonnegative"),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_lines_purchase_id", "purchase_lines", ["purchase_id"])
    op.create_index("ix_purchase_lines_product_id", "purchase_lines", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_lines_product_id", table_name="purchase_lines")
    op.drop_index("ix_purchase_lines_purchase_id", table_name="purchase_lines")
    op.drop_table("purchase_lines")
    op.drop_index("ix_purchases_supplier_id", table_name="purchases")
    op.drop_index("ix_purchases_site_id", table_name="purchases")
    op.drop_index("ix_purchases_company_id", table_name="purchases")
    op.drop_table("purchases")
    op.drop_index("ix_suppliers_company_id", table_name="suppliers")
    op.drop_table("suppliers")
