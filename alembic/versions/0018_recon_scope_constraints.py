"""Enforce company and bank-account scope with composite foreign keys."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_recon_scope_constraints"
down_revision: Union[str, None] = "0017_bank_recon_adjustments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_existing_rows_have_valid_scope() -> None:
    checks = {
        "bank statement imports with mismatched company/account": """
            SELECT count(*) FROM bank_statement_imports i
            JOIN bank_accounts a ON a.id = i.bank_account_id
            WHERE i.company_id <> a.company_id
        """,
        "bank transactions with mismatched company/account": """
            SELECT count(*) FROM bank_transactions t
            JOIN bank_accounts a ON a.id = t.bank_account_id
            WHERE t.company_id <> a.company_id
        """,
        "statement lines with mismatched import/account scope": """
            SELECT count(*) FROM bank_statement_lines l
            JOIN bank_statement_imports i ON i.id = l.import_id
            JOIN bank_accounts a ON a.id = l.bank_account_id
            WHERE l.company_id <> i.company_id
               OR l.bank_account_id <> i.bank_account_id
               OR l.company_id <> a.company_id
        """,
        "duplicate links crossing company/account scope": """
            SELECT count(*) FROM bank_statement_lines l
            JOIN bank_statement_lines parent ON parent.id = l.duplicate_of_line_id
            WHERE l.company_id <> parent.company_id
               OR l.bank_account_id <> parent.bank_account_id
        """,
        "matched transaction links crossing company/account scope": """
            SELECT count(*) FROM bank_statement_lines l
            JOIN bank_transactions t ON t.id = l.matched_bank_transaction_id
            WHERE l.company_id <> t.company_id
               OR l.bank_account_id <> t.bank_account_id
        """,
        "transaction statement links crossing company/account scope": """
            SELECT count(*) FROM bank_transactions t
            JOIN bank_statement_lines l ON l.id = t.statement_line_id
            WHERE t.company_id <> l.company_id
               OR t.bank_account_id <> l.bank_account_id
        """,
        "reconciliation snapshots with mismatched import/account scope": """
            SELECT count(*) FROM bank_reconciliation_snapshots s
            JOIN bank_statement_imports i ON i.id = s.import_id
            JOIN bank_accounts a ON a.id = s.bank_account_id
            WHERE s.company_id <> i.company_id
               OR s.bank_account_id <> i.bank_account_id
               OR s.company_id <> a.company_id
        """,
    }
    connection = op.get_bind()
    invalid = {
        description: connection.execute(sa.text(query)).scalar_one()
        for description, query in checks.items()
    }
    invalid = {description: count for description, count in invalid.items() if count}
    if invalid:
        details = "; ".join(f"{description}: {count}" for description, count in invalid.items())
        raise RuntimeError(
            "Cannot add reconciliation scope constraints because existing rows violate "
            f"company/account ownership. Repair these rows first: {details}"
        )


def upgrade() -> None:
    _assert_existing_rows_have_valid_scope()
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
