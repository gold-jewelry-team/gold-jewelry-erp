"""Add imported bank statements and reconciliation lines.
Revision ID: 0015_bank_statement_reconciliation
Revises: 0014_bank_accounts_ledger
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str="0015_bank_statement_reconciliation"
down_revision: Union[str,None]="0014_bank_accounts_ledger"
branch_labels: Union[str,Sequence[str],None]=None
depends_on: Union[str,Sequence[str],None]=None

def upgrade()->None:
    op.create_table(
        "bank_statement_imports",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("bank_account_id",sa.Uuid(),nullable=False),
        sa.Column("source_file_name",sa.String(200),nullable=False),
        sa.Column("row_count",sa.Integer(),nullable=False),
        sa.Column("status",sa.String(20),server_default="IMPORTED",nullable=False),
        sa.Column("imported_by_name",sa.String(120),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("status IN ('IMPORTED','REVIEWED')",name="ck_bank_statement_imports_status"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_account_id"],["bank_accounts.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_statement_imports_account_created","bank_statement_imports",["bank_account_id","created_at"])
    op.create_table(
        "bank_statement_lines",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("import_id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("bank_account_id",sa.Uuid(),nullable=False),
        sa.Column("transaction_date",sa.Date(),nullable=False),
        sa.Column("description",sa.String(300),nullable=False),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),
        sa.Column("direction",sa.String(3),nullable=False),
        sa.Column("reference_no",sa.String(100),nullable=True),
        sa.Column("fingerprint",sa.String(64),nullable=False),
        sa.Column("status",sa.String(20),server_default="UNMATCHED",nullable=False),
        sa.Column("matched_bank_transaction_id",sa.Uuid(),nullable=True),
        sa.Column("duplicate_of_line_id",sa.Uuid(),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("direction IN ('IN','OUT')",name="ck_bank_statement_lines_direction"),
        sa.CheckConstraint("amount > 0",name="ck_bank_statement_lines_amount_positive"),
        sa.CheckConstraint("status IN ('UNMATCHED','MATCHED','DUPLICATE','IGNORED')",name="ck_bank_statement_lines_status"),
        sa.ForeignKeyConstraint(["import_id"],["bank_statement_imports.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_account_id"],["bank_accounts.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["matched_bank_transaction_id"],["bank_transactions.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["duplicate_of_line_id"],["bank_statement_lines.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("matched_bank_transaction_id",name="uq_bank_statement_lines_matched_transaction"),
    )
    op.create_index("ix_bank_statement_lines_import_status","bank_statement_lines",["import_id","status"])
    op.create_index("ix_bank_statement_lines_account_date_amount","bank_statement_lines",["bank_account_id","transaction_date","amount"])

def downgrade()->None:
    op.drop_index("ix_bank_statement_lines_account_date_amount",table_name="bank_statement_lines")
    op.drop_index("ix_bank_statement_lines_import_status",table_name="bank_statement_lines")
    op.drop_table("bank_statement_lines")
    op.drop_index("ix_bank_statement_imports_account_created",table_name="bank_statement_imports")
    op.drop_table("bank_statement_imports")
