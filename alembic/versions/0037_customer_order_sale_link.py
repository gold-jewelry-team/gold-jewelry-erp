"""Link each customer order to one formal sale.

Revision ID: 0037_customer_order_sale_link
Revises: 0036_supplier_payment_reversals
Create Date: 2026-11-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037_customer_order_sale_link"
down_revision: Union[str, None] = "0036_supplier_payment_reversals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The quoted estimate may be lower than the final delivery-date sale amount.
    # The final sale amount is the collection ceiling after a sale draft is linked.
    op.drop_constraint("ck_customer_orders_amounts", "customer_orders", type_="check")
    op.create_check_constraint(
        "ck_customer_orders_amounts",
        "customer_orders",
        "total_amount > 0 AND deposit_amount >= 0",
    )
    op.add_column(
        "customer_orders",
        sa.Column("final_sale_amount", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "sales",
        sa.Column("customer_order_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_customer_order_id_customer_orders",
        "sales",
        "customer_orders",
        ["customer_order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_sales_customer_order_id",
        "sales",
        ["customer_order_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_sales_customer_order_id", "sales", type_="unique")
    op.drop_constraint("fk_sales_customer_order_id_customer_orders", "sales", type_="foreignkey")
    op.drop_column("sales", "customer_order_id")
    op.drop_column("customer_orders", "final_sale_amount")
    op.drop_constraint("ck_customer_orders_amounts", "customer_orders", type_="check")
    op.create_check_constraint(
        "ck_customer_orders_amounts",
        "customer_orders",
        "total_amount > 0 AND deposit_amount >= 0 AND deposit_amount <= total_amount",
    )
