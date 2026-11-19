"""Add product master data and inventory movement ledger.

Revision ID: 0004_products_inventory
Revises: 0003_sales_snapshots
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_products_inventory"
down_revision: Union[str, None] = "0003_sales_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(code) > 0", name="ck_product_categories_code_nonempty"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["product_categories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_product_categories_company_code"),
    )
    op.create_index("ix_product_categories_company_id", "product_categories", ["company_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("product_code", sa.String(50), nullable=False),
        sa.Column("barcode", sa.String(100), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("material_code", sa.String(30), nullable=True),
        sa.Column("gross_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("net_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("weight_unit_code", sa.String(20), server_default="QIAN", nullable=False),
        sa.Column("labor_fee", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(product_code) > 0", name="ck_products_code_nonempty"),
        sa.CheckConstraint("length(name) > 0", name="ck_products_name_nonempty"),
        sa.CheckConstraint("gross_weight >= 0", name="ck_products_gross_weight_nonnegative"),
        sa.CheckConstraint("net_weight >= 0", name="ck_products_net_weight_nonnegative"),
        sa.CheckConstraint("labor_fee >= 0", name="ck_products_labor_fee_nonnegative"),
        sa.CheckConstraint("net_weight <= gross_weight", name="ck_products_net_not_over_gross"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "product_code", name="uq_products_company_code"),
        sa.UniqueConstraint("company_id", "barcode", name="uq_products_company_barcode"),
    )
    op.create_index("ix_products_company_id", "products", ["company_id"])
    op.create_index("ix_products_category_id", "products", ["category_id"])

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("from_location_id", sa.Uuid(), nullable=True),
        sa.Column("to_location_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), server_default="1", nullable=False),
        sa.Column("weight", sa.Numeric(18, 4), nullable=True),
        sa.Column("weight_unit_code", sa.String(20), nullable=True),
        sa.Column("reference_type", sa.String(30), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("movement_type IN ('RECEIPT', 'SALE', 'TRANSFER', 'ADJUSTMENT', 'RETURN', 'REPAIR_SEND', 'REPAIR_RETURN')", name="ck_inventory_movements_type"),
        sa.CheckConstraint("quantity > 0", name="ck_inventory_movements_quantity_positive"),
        sa.CheckConstraint("weight IS NULL OR weight >= 0", name="ck_inventory_movements_weight_nonnegative"),
        sa.CheckConstraint("(from_location_id IS NOT NULL OR to_location_id IS NOT NULL) AND (from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id)", name="ck_inventory_movements_locations"),
        sa.CheckConstraint("(movement_type = 'TRANSFER' AND from_location_id IS NOT NULL AND to_location_id IS NOT NULL) OR (movement_type <> 'TRANSFER')", name="ck_inventory_movements_transfer_locations"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["from_location_id"], ["storage_locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_location_id"], ["storage_locations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_movements_company_id", "inventory_movements", ["company_id"])
    op.create_index("ix_inventory_movements_site_id", "inventory_movements", ["site_id"])
    op.create_index("ix_inventory_movements_company_product_time", "inventory_movements", ["company_id", "product_id", "occurred_at"])
    op.create_index("ix_inventory_movements_from_location", "inventory_movements", ["from_location_id", "occurred_at"])
    op.create_index("ix_inventory_movements_to_location", "inventory_movements", ["to_location_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_to_location", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_from_location", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_company_product_time", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_site_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_company_id", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_index("ix_products_category_id", table_name="products")
    op.drop_index("ix_products_company_id", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_product_categories_company_id", table_name="product_categories")
    op.drop_table("product_categories")
