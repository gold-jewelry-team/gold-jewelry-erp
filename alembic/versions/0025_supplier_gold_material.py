"""Add fine-gold material ledger and supplier gold settlement allocations.

Revision ID: 0025_supplier_gold_material
Revises: 0024_labor_code_settings
Create Date: 2026-11-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0025_supplier_gold_material"
down_revision: Union[str, None] = "0024_labor_code_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gold_material_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purchase_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("movement_no", sa.String(50), nullable=False),
        sa.Column("movement_type", sa.String(24), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=True),
        sa.Column("purity_label", sa.String(30), nullable=False),
        sa.Column("purity_ratio", sa.Numeric(8, 6), nullable=False),
        sa.Column("gross_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("loss_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("net_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("weight_unit_code", sa.String(10), nullable=False),
        sa.Column("fine_gold_weight_g", sa.Numeric(18, 4), nullable=False),
        sa.Column("gold_price_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("gold_price_unit_code", sa.String(10), nullable=False),
        sa.Column("deduction_amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("valuation_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "movement_type IN ('OPENING', 'RECEIPT', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'SUPPLIER_DELIVERY')",
            name="ck_gold_material_movements_type",
        ),
        sa.CheckConstraint("purity_ratio > 0 AND purity_ratio <= 1", name="ck_gold_material_purity_ratio"),
        sa.CheckConstraint("gross_weight > 0 AND loss_weight >= 0 AND net_weight > 0", name="ck_gold_material_weights"),
        sa.CheckConstraint("fine_gold_weight_g > 0", name="ck_gold_material_fine_weight"),
        sa.CheckConstraint("gold_price_value > 0 AND deduction_amount >= 0 AND valuation_amount > 0", name="ck_gold_material_valuation"),
        sa.CheckConstraint("weight_unit_code IN ('G', 'QIAN', 'LIANG')", name="ck_gold_material_weight_unit"),
        sa.CheckConstraint("gold_price_unit_code IN ('G', 'QIAN', 'LIANG')", name="ck_gold_material_price_unit"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "movement_no", name="uq_gold_material_site_movement_no"),
    )
    op.create_index("ix_gold_material_company_site_time", "gold_material_movements", ["company_id", "site_id", "occurred_at"])
    op.create_index("ix_gold_material_purchase_id", "gold_material_movements", ["purchase_id"])
    op.create_index("ix_gold_material_supplier_id", "gold_material_movements", ["supplier_id"])

    op.create_table(
        "gold_material_settlement_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("movement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_gold_material_settlement_amount_positive"),
        sa.ForeignKeyConstraint(["movement_id"], ["gold_material_movements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bill_id"], ["supplier_bills.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movement_id", "bill_id", name="uq_gold_material_settlement_movement_bill"),
    )
    op.create_index("ix_gold_material_settlement_bill_id", "gold_material_settlement_allocations", ["bill_id"])


def downgrade() -> None:
    op.drop_index("ix_gold_material_settlement_bill_id", table_name="gold_material_settlement_allocations")
    op.drop_table("gold_material_settlement_allocations")
    op.drop_index("ix_gold_material_supplier_id", table_name="gold_material_movements")
    op.drop_index("ix_gold_material_purchase_id", table_name="gold_material_movements")
    op.drop_index("ix_gold_material_company_site_time", table_name="gold_material_movements")
    op.drop_table("gold_material_movements")
