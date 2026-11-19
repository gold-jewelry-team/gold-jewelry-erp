"""Add immutable bank reconciliation snapshots.
Revision ID: 0016_bank_reconciliation_snapshots
Revises: 0015_bank_statement_reconciliation
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str="0016_bank_reconciliation_snapshots"
down_revision: Union[str,None]="0015_bank_statement_reconciliation"
branch_labels: Union[str,Sequence[str],None]=None
depends_on: Union[str,Sequence[str],None]=None

def upgrade()->None:
    op.create_table(
        "bank_reconciliation_snapshots",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("bank_account_id",sa.Uuid(),nullable=False),
        sa.Column("import_id",sa.Uuid(),nullable=False),
        sa.Column("period_start",sa.Date(),nullable=False),
        sa.Column("period_end",sa.Date(),nullable=False),
        sa.Column("statement_opening_balance",sa.Numeric(18,2),nullable=False),
        sa.Column("statement_closing_balance",sa.Numeric(18,2),nullable=False),
        sa.Column("statement_net_movement",sa.Numeric(18,2),nullable=False),
        sa.Column("ledger_net_movement",sa.Numeric(18,2),nullable=False),
        sa.Column("balance_difference",sa.Numeric(18,2),nullable=False),
        sa.Column("net_difference",sa.Numeric(18,2),nullable=False),
        sa.Column("statement_line_count",sa.Integer(),nullable=False),
        sa.Column("matched_line_count",sa.Integer(),nullable=False),
        sa.Column("unmatched_line_count",sa.Integer(),nullable=False),
        sa.Column("duplicate_line_count",sa.Integer(),nullable=False),
        sa.Column("ignored_line_count",sa.Integer(),nullable=False),
        sa.Column("unmatched_ledger_count",sa.Integer(),nullable=False),
        sa.Column("status",sa.String(20),nullable=False),
        sa.Column("reconciled_by_name",sa.String(120),nullable=False),
        sa.Column("note",sa.String(500),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("period_end >= period_start",name="ck_bank_reconciliation_period_order"),
        sa.CheckConstraint("status IN ('RECONCILED','NEEDS_REVIEW')",name="ck_bank_reconciliation_status"),
        sa.CheckConstraint("statement_line_count >= 0 AND matched_line_count >= 0 AND unmatched_line_count >= 0 AND duplicate_line_count >= 0 AND ignored_line_count >= 0 AND unmatched_ledger_count >= 0",name="ck_bank_reconciliation_counts_nonnegative"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_account_id"],["bank_accounts.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["import_id"],["bank_statement_imports.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_reconciliation_account_period","bank_reconciliation_snapshots",["bank_account_id","period_start","period_end"])

def downgrade()->None:
    op.drop_index("ix_bank_reconciliation_account_period",table_name="bank_reconciliation_snapshots")
    op.drop_table("bank_reconciliation_snapshots")
