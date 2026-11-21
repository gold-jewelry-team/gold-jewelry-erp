"""Add customer special orders and separate deposit payment ledger.

Revision ID: 0027_customer_orders_deposits
Revises: 0026_supplier_product_catalog
Create Date: 2026-11-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0027_customer_orders_deposits"
down_revision: Union[str, None] = "0026_supplier_product_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_no", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), server_default="PENDING_DEPOSIT", nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("customer_phone", sa.String(40), nullable=True),
        sa.Column("expected_delivery_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency_code", sa.String(3), server_default="TWD", nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("deposit_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING_DEPOSIT', 'IN_PROGRESS', 'ARRIVED', 'READY', 'COMPLETED', 'CANCELLED')", name="ck_customer_orders_status"),
        sa.CheckConstraint("total_amount >= 0 AND deposit_amount >= 0 AND deposit_amount <= total_amount", name="ck_customer_orders_amounts"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "order_no", name="uq_customer_orders_site_order_no"),
    )
    op.create_index("ix_customer_orders_company_site_created", "customer_orders", ["company_id", "site_id", "created_at"])
    op.add_column("payment_transactions", sa.Column("customer_order_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_payment_transactions_customer_order_id_customer_orders",
        "payment_transactions", "customer_orders", ["customer_order_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_payment_transactions_customer_order_id", "payment_transactions", ["customer_order_id"])
    op.drop_constraint("ck_payment_transactions_exactly_one_source", "payment_transactions", type_="check")
    op.create_check_constraint(
        "ck_payment_transactions_exactly_one_source",
        "payment_transactions",
        "(sale_id IS NOT NULL AND sale_return_id IS NULL AND customer_order_id IS NULL) OR "
        "(sale_id IS NULL AND sale_return_id IS NOT NULL AND customer_order_id IS NULL) OR "
        "(sale_id IS NULL AND sale_return_id IS NULL AND customer_order_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payment_transactions_exactly_one_source", "payment_transactions", type_="check")
    op.drop_index("ix_payment_transactions_customer_order_id", table_name="payment_transactions")
    op.drop_constraint("fk_payment_transactions_customer_order_id_customer_orders", "payment_transactions", type_="foreignkey")
    op.drop_column("payment_transactions", "customer_order_id")
    op.create_check_constraint(
        "ck_payment_transactions_exactly_one_source",
        "payment_transactions",
        "(sale_id IS NOT NULL AND sale_return_id IS NULL) OR "
        "(sale_id IS NULL AND sale_return_id IS NOT NULL)",
    )
    op.drop_index("ix_customer_orders_company_site_created", table_name="customer_orders")
    op.drop_table("customer_orders")
