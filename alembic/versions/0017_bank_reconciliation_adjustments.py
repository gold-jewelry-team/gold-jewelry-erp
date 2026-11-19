"""Add statement-linked bank adjustment transactions.
Revision ID: 0017_bank_recon_adjustments
Revises: 0016_bank_recon_snapshots
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str="0017_bank_recon_adjustments"
down_revision: Union[str,None]="0016_bank_recon_snapshots"
branch_labels: Union[str,Sequence[str],None]=None
depends_on: Union[str,Sequence[str],None]=None

def upgrade()->None:
    with op.batch_alter_table("bank_transactions") as batch:
        batch.drop_constraint("ck_bank_transactions_type",type_="check")
        batch.drop_constraint("ck_bank_transactions_type_direction",type_="check")
        batch.add_column(sa.Column("statement_line_id",sa.Uuid(),nullable=True))
        batch.create_foreign_key("fk_bank_transactions_statement_line_id_bank_statement_lines","bank_statement_lines",["statement_line_id"],["id"],ondelete="RESTRICT")
        batch.create_check_constraint("ck_bank_transactions_type","transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT','BANK_FEE','INTEREST_IN','OTHER_ADJUSTMENT')")
        batch.create_check_constraint("ck_bank_transactions_type_direction","(transaction_type IN ('CASH_DEPOSIT','TRANSFER_IN','INTEREST_IN') AND direction = 'IN') OR (transaction_type IN ('CASH_WITHDRAWAL','TRANSFER_OUT','BANK_FEE') AND direction = 'OUT') OR transaction_type = 'OTHER_ADJUSTMENT'")
        batch.create_index("ix_bank_transactions_statement_line",["statement_line_id"],unique=True)

def downgrade()->None:
    with op.batch_alter_table("bank_transactions") as batch:
        batch.drop_index("ix_bank_transactions_statement_line")
        batch.drop_constraint("fk_bank_transactions_statement_line_id_bank_statement_lines",type_="foreignkey")
        batch.drop_column("statement_line_id")
        batch.drop_constraint("ck_bank_transactions_type",type_="check")
        batch.drop_constraint("ck_bank_transactions_type_direction",type_="check")
        batch.create_check_constraint("ck_bank_transactions_type","transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT')")
        batch.create_check_constraint("ck_bank_transactions_type_direction","(transaction_type IN ('CASH_DEPOSIT','TRANSFER_IN') AND direction = 'IN') OR (transaction_type IN ('CASH_WITHDRAWAL','TRANSFER_OUT') AND direction = 'OUT')")
