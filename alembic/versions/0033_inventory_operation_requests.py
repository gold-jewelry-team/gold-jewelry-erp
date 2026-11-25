"""Add durable inventory operation request registry.

Revision ID: 0033_inventory_op_requests
Revises: 0032_bank_operation_idempotency
Create Date: 2026-11-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0033_inventory_op_requests"
down_revision: Union[str, None] = "0032_bank_operation_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_operation_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("movement_id", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=60), nullable=True),
        sa.Column("failure_message", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation_type IN ('MANUAL_ADJUSTMENT', 'MANUAL_TRANSFER')",
            name="ck_inventory_operation_requests_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED')",
            name="ck_inventory_operation_requests_status",
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND movement_id IS NOT NULL) OR "
            "(status <> 'COMPLETED' AND movement_id IS NULL)",
            name="ck_inventory_operation_requests_completed_movement",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["movement_id"], ["inventory_movements.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "idempotency_key",
            name="uq_inventory_operation_requests_company_key",
        ),
    )
    op.create_index(
        "ix_inventory_operation_requests_company_site_status_created",
        "inventory_operation_requests",
        ["company_id", "site_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_operation_requests_company_site_status_created",
        table_name="inventory_operation_requests",
    )
    op.drop_table("inventory_operation_requests")
