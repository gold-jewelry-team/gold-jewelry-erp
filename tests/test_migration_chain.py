from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_history_is_a_single_linear_chain_through_bank_statement_reconciliation():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0015_bank_statement_reconciliation"]

    expected = [
        "0015_bank_statement_reconciliation",
        "0014_bank_accounts_ledger",
        "0013_cash_drawer_movements",
        "0012_daily_cash_counts",
        "0011_operating_expenses",
        "0010_supplier_payables",
        "0009_payment_transactions",
        "0008_daily_closing",
        "0007_sales_returns",
        "0006_sales_inventory_links",
        "0005_suppliers_purchasing",
        "0004_products_inventory",
        "0003_sales_snapshots",
        "0002_gold_prices",
        "0001_core",
    ]
    for current, parent in zip(expected, expected[1:]):
        revision = script.get_revision(current)
        assert revision is not None
        assert revision.down_revision == parent

    root = script.get_revision(expected[-1])
    assert root is not None
    assert root.down_revision is None
