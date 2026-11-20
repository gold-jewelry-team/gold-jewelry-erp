"""Add supplier category and product offerings; seed default jewelry categories.

Revision ID: 0026_supplier_product_catalog
Revises: 0025_supplier_gold_material
Create Date: 2026-11-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0026_supplier_product_catalog"
down_revision: Union[str, None] = "0025_supplier_gold_material"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_CATEGORIES = (
    ("PAIR_RING", "對戒", 10),
    ("WOMENS_RING", "女戒", 20),
    ("ADJUSTABLE_PINKY_RING", "可調式尾戒", 30),
    ("FIXED_PINKY_RING", "固定圍尾戒", 40),
    ("OPEN_BRACELET", "開口式手環", 50),
    ("FIXED_BRACELET", "固定圍手環", 60),
    ("WOMENS_PENDANT", "女墜", 70),
    ("MENS_PENDANT", "男墜", 80),
    ("WOMENS_CHAIN_BRACELET", "女手鏈", 90),
    ("MENS_CHAIN_BRACELET", "男手鏈", 100),
    ("RED_STRING", "紅線", 110),
    ("EARRINGS", "耳環", 120),
    ("NECKLACE_SET", "套鏈", 130),
    ("CHILD_BRACELET", "童手環", 140),
    ("GOLD_NUGGET", "小金塊", 150),
)


def upgrade() -> None:
    op.create_unique_constraint("uq_suppliers_id_company", "suppliers", ["id", "company_id"])
    op.create_unique_constraint("uq_product_categories_id_company", "product_categories", ["id", "company_id"])
    op.create_unique_constraint("uq_products_id_company", "products", ["id", "company_id"])

    op.create_table(
        "supplier_category_offerings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(12), server_default="ACTIVE", nullable=False),
        sa.Column("is_preferred", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supplier_category_name", sa.String(120), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'PAUSED', 'STOPPED')", name="ck_supplier_category_offerings_status"),
        sa.ForeignKeyConstraint(["supplier_id", "company_id"], ["suppliers.id", "suppliers.company_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_id", "company_id"], ["product_categories.id", "product_categories.company_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "supplier_id", "category_id", name="uq_supplier_category_offering"),
    )
    op.create_index("ix_supplier_category_offerings_company_category", "supplier_category_offerings", ["company_id", "category_id", "status"])
    op.create_index("ix_supplier_category_offerings_supplier", "supplier_category_offerings", ["company_id", "supplier_id", "status"])

    op.create_table(
        "supplier_product_offerings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_product_code", sa.String(80), nullable=True),
        sa.Column("quoted_unit_cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency_code", sa.String(3), server_default="TWD", nullable=False),
        sa.Column("min_order_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(12), server_default="ACTIVE", nullable=False),
        sa.Column("is_preferred", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("last_quoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'PAUSED', 'STOPPED')", name="ck_supplier_product_offerings_status"),
        sa.CheckConstraint("quoted_unit_cost IS NULL OR quoted_unit_cost >= 0", name="ck_supplier_product_offerings_cost_nonnegative"),
        sa.CheckConstraint("min_order_quantity IS NULL OR min_order_quantity > 0", name="ck_supplier_product_offerings_min_qty_positive"),
        sa.CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_supplier_product_offerings_lead_time_nonnegative"),
        sa.ForeignKeyConstraint(["supplier_id", "company_id"], ["suppliers.id", "suppliers.company_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "supplier_id", "product_id", name="uq_supplier_product_offering"),
    )
    op.create_index("ix_supplier_product_offerings_company_product", "supplier_product_offerings", ["company_id", "product_id", "status"])
    op.create_index("ix_supplier_product_offerings_supplier", "supplier_product_offerings", ["company_id", "supplier_id", "status"])

    connection = op.get_bind()
    companies = connection.execute(sa.text("SELECT id FROM companies")).scalars().all()
    for company_id in companies:
        existing = set(connection.execute(
            sa.text("SELECT code FROM product_categories WHERE company_id = :company_id"),
            {"company_id": company_id},
        ).scalars().all())
        for code, name, sort_order in DEFAULT_CATEGORIES:
            if code not in existing:
                connection.execute(
                    sa.text("""
                        INSERT INTO product_categories
                            (id, company_id, code, name, sort_order, is_active, created_at)
                        VALUES
                            (:id, :company_id, :code, :name, :sort_order, true, now())
                    """),
                    {
                        "id": __import__("uuid").uuid4(),
                        "company_id": company_id,
                        "code": code,
                        "name": name,
                        "sort_order": sort_order,
                    },
                )


def downgrade() -> None:
    op.drop_index("ix_supplier_product_offerings_supplier", table_name="supplier_product_offerings")
    op.drop_index("ix_supplier_product_offerings_company_product", table_name="supplier_product_offerings")
    op.drop_table("supplier_product_offerings")
    op.drop_index("ix_supplier_category_offerings_supplier", table_name="supplier_category_offerings")
    op.drop_index("ix_supplier_category_offerings_company_category", table_name="supplier_category_offerings")
    op.drop_table("supplier_category_offerings")
    op.drop_constraint("uq_products_id_company", "products", type_="unique")
    op.drop_constraint("uq_product_categories_id_company", "product_categories", type_="unique")
    op.drop_constraint("uq_suppliers_id_company", "suppliers", type_="unique")
