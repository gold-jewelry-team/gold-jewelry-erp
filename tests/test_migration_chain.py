from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_history_is_a_single_linear_chain_through_customer_order_sale_link():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0037_customer_order_sale_link"]

    expected = [
        "0037_customer_order_sale_link",
        "0036_supplier_payment_reversals",
        "0035_company_role_permissions",
        "0034_user_identity_memberships",
        "0033_inventory_op_requests",
        "0032_bank_operation_idempotency",
        "0031_bank_transfer_source_links",
        "0030_payment_idempotency",
        "0029_cash_drawer_idempotency",
        "0028_estimate_sale_returns",
        "0027_customer_orders_deposits",
        "0026_supplier_product_catalog",
        "0025_supplier_gold_material",
        "0024_labor_code_settings",
        "0023_purchase_labor_cost",
        "0022_product_label_details",
        "0021_product_code_sequence",
        "0020_sales_card_tender",
        "0019_daily_closing_mixed_payment",
        "0018_recon_scope_constraints",
        "0017_bank_recon_adjustments",
        "0016_bank_recon_snapshots",
        "0015_bank_stmt_reconcile",
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


def test_docker_startup_does_not_apply_production_migrations():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "alembic upgrade head" not in dockerfile
    assert "exec uvicorn app.main:app" in dockerfile
