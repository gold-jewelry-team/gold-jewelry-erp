"""Enforce company and bank-account scope with composite foreign keys."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_recon_scope_constraints"
down_revision: Union[str, None] = "0017_bank_recon_adjustments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite candidate keys make the ownership scope part of every FK.
    op.create_unique_constraint("uq_bank_accounts_id_company", "bank_accounts", ["id", "company_id"])
    op.create_unique_constraint("uq_bank_statement_imports_id_scope", "bank_statement_imports", ["id", "company_id", "bank_account_id"])
    op.create_unique_constraint("uq_bank_statement_lines_id_scope", "bank_statement_lines", ["id", "company_id", "bank_account_id"])
    op.create_unique_constraint("uq_bank_transactions_id_scope", "bank_transactions", ["id", "company_id", "bank_account_id"])

    op.create_foreign_key(
        "fk_bank_statement_imports_account_company",
        "bank_statement_imports", "bank_accounts",
        ["bank_account_id", "company_id"], ["id", "company_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_transactions_account_company",
        "bank_transactions", "bank_accounts",
        ["bank_account_id", "company_id"], ["id", "company_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_statement_lines_account_company",
        "bank_statement_lines", "bank_accounts",
        ["bank_account_id", "company_id"], ["id", "company_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_statement_lines_import_scope",
        "bank_statement_lines", "bank_statement_imports",
        ["import_id", "company_id", "bank_account_id"],
        ["id", "company_id", "bank_account_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_statement_lines_duplicate_scope",
        "bank_statement_lines", "bank_statement_lines",
        ["duplicate_of_line_id", "company_id", "bank_account_id"],
        ["id", "company_id", "bank_account_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_statement_lines_matched_tx_scope",
        "bank_statement_lines", "bank_transactions",
        ["matched_bank_transaction_id", "company_id", "bank_account_id"],
        ["id", "company_id", "bank_account_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_transactions_statement_line_scope",
        "bank_transactions", "bank_statement_lines",
        ["statement_line_id", "company_id", "bank_account_id"],
        ["id", "company_id", "bank_account_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_reconciliation_account_company",
        "bank_reconciliation_snapshots", "bank_accounts",
        ["bank_account_id", "company_id"], ["id", "company_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bank_reconciliation_import_scope",
        "bank_reconciliation_snapshots", "bank_statement_imports",
        ["import_id", "company_id", "bank_account_id"],
        ["id", "company_id", "bank_account_id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_bank_reconciliation_import_scope", "bank_reconciliation_snapshots", type_="foreignkey")
    op.drop_constraint("fk_bank_reconciliation_account_company", "bank_reconciliation_snapshots", type_="foreignkey")
    op.drop_constraint("fk_bank_transactions_statement_line_scope", "bank_transactions", type_="foreignkey")
    op.drop_constraint("fk_bank_statement_lines_matched_tx_scope", "bank_statement_lines", type_="foreignkey")
    op.drop_constraint("fk_bank_statement_lines_duplicate_scope", "bank_statement_lines", type_="foreignkey")
    op.drop_constraint("fk_bank_statement_lines_import_scope", "bank_statement_lines", type_="foreignkey")
    op.drop_constraint("fk_bank_statement_lines_account_company", "bank_statement_lines", type_="foreignkey")
    op.drop_constraint("fk_bank_transactions_account_company", "bank_transactions", type_="foreignkey")
    op.drop_constraint("fk_bank_statement_imports_account_company", "bank_statement_imports", type_="foreignkey")

    op.drop_constraint("uq_bank_transactions_id_scope", "bank_transactions", type_="unique")
    op.drop_constraint("uq_bank_statement_lines_id_scope", "bank_statement_lines", type_="unique")
    op.drop_constraint("uq_bank_statement_imports_id_scope", "bank_statement_imports", type_="unique")
    op.drop_constraint("uq_bank_accounts_id_company", "bank_accounts", type_="unique")
