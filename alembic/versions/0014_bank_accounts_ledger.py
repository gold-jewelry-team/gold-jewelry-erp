"""Add bank accounts, bank transaction ledger and cash links.
Revision ID: 0014_bank_accounts_ledger
Revises: 0013_cash_drawer_movements
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str="0014_bank_accounts_ledger"
down_revision: Union[str,None]="0013_cash_drawer_movements"
branch_labels: Union[str,Sequence[str],None]=None
depends_on: Union[str,Sequence[str],None]=None

def upgrade()->None:
    op.create_table(
        "bank_accounts",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("bank_name",sa.String(100),nullable=False),
        sa.Column("account_name",sa.String(120),nullable=False),
        sa.Column("account_last4",sa.String(4),nullable=False),
        sa.Column("currency_code",sa.String(3),server_default="TWD",nullable=False),
        sa.Column("opening_balance",sa.Numeric(18,2),server_default="0",nullable=False),
        sa.Column("opening_balance_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("is_active",sa.Boolean(),server_default=sa.true(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("currency_code = 'TWD'",name="ck_bank_accounts_currency_twd"),
        sa.CheckConstraint("opening_balance >= 0",name="ck_bank_accounts_opening_balance_nonnegative"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_accounts_company_active","bank_accounts",["company_id","is_active"])
    op.create_table(
        "bank_transactions",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("bank_account_id",sa.Uuid(),nullable=False),
        sa.Column("site_id",sa.Uuid(),nullable=True),
        sa.Column("transfer_group_id",sa.Uuid(),nullable=True),
        sa.Column("transaction_type",sa.String(20),nullable=False),
        sa.Column("direction",sa.String(3),nullable=False),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),
        sa.Column("currency_code",sa.String(3),server_default="TWD",nullable=False),
        sa.Column("reference_no",sa.String(100),nullable=True),
        sa.Column("description",sa.String(200),nullable=False),
        sa.Column("created_by_name",sa.String(120),nullable=False),
        sa.Column("occurred_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("note",sa.String(500),nullable=True),
        sa.CheckConstraint("direction IN ('IN','OUT')",name="ck_bank_transactions_direction"),
        sa.CheckConstraint("transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT')",name="ck_bank_transactions_type"),
        sa.CheckConstraint("amount > 0",name="ck_bank_transactions_amount_positive"),
        sa.CheckConstraint("currency_code = 'TWD'",name="ck_bank_transactions_currency_twd"),
        sa.CheckConstraint("(transaction_type IN ('CASH_DEPOSIT','TRANSFER_IN') AND direction = 'IN') OR (transaction_type IN ('CASH_WITHDRAWAL','TRANSFER_OUT') AND direction = 'OUT')",name="ck_bank_transactions_type_direction"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_account_id"],["bank_accounts.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"],["sites.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_transactions_account_occurred","bank_transactions",["bank_account_id","occurred_at"])
    op.create_index("ix_bank_transactions_company_site_occurred","bank_transactions",["company_id","site_id","occurred_at"])
    op.add_column("cash_drawer_movements",sa.Column("bank_transaction_id",sa.Uuid(),nullable=True))
    op.create_unique_constraint("uq_cash_drawer_movements_bank_transaction","cash_drawer_movements",["bank_transaction_id"])
    op.create_foreign_key("fk_cash_drawer_movements_bank_transaction","cash_drawer_movements","bank_transactions",["bank_transaction_id"],["id"],ondelete="RESTRICT")

def downgrade()->None:
    op.drop_constraint("fk_cash_drawer_movements_bank_transaction","cash_drawer_movements",type_="foreignkey")
    op.drop_constraint("uq_cash_drawer_movements_bank_transaction","cash_drawer_movements",type_="unique")
    op.drop_column("cash_drawer_movements","bank_transaction_id")
    op.drop_index("ix_bank_transactions_company_site_occurred",table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_account_occurred",table_name="bank_transactions")
    op.drop_table("bank_transactions")
    op.drop_index("ix_bank_accounts_company_active",table_name="bank_accounts")
    op.drop_table("bank_accounts")
