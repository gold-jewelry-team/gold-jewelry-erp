"""Link sales lines to inventory products and source locations.

Revision ID: 0006_sales_inventory_links
Revises: 0005_suppliers_purchasing
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_sales_inventory_links"
down_revision: Union[str, None] = "0005_suppliers_purchasing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sale_lines", sa.Column("product_id", sa.Uuid(), nullable=True))
    op.add_column("sale_lines", sa.Column("source_location_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sale_lines_product_id_products",
        "sale_lines",
        "products",
        ["product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_sale_lines_source_location_id_storage_locations",
        "sale_lines",
        "storage_locations",
        ["source_location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_sale_lines_product_id", "sale_lines", ["product_id"])
    op.create_index("ix_sale_lines_source_location_id", "sale_lines", ["source_location_id"])


def downgrade() -> None:
    op.drop_index("ix_sale_lines_source_location_id", table_name="sale_lines")
    op.drop_index("ix_sale_lines_product_id", table_name="sale_lines")
    op.drop_constraint("fk_sale_lines_source_location_id_storage_locations", "sale_lines", type_="foreignkey")
    op.drop_constraint("fk_sale_lines_product_id_products", "sale_lines", type_="foreignkey")
    op.drop_column("sale_lines", "source_location_id")
    op.drop_column("sale_lines", "product_id")
