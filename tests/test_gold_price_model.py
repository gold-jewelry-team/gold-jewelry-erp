from app.db.base import Base
from app import models  # noqa: F401


def test_gold_price_table_is_registered() -> None:
    assert "gold_prices" in Base.metadata.tables


def test_gold_price_has_required_history_fields() -> None:
    table = Base.metadata.tables["gold_prices"]
    assert {
        "company_id",
        "site_id",
        "price_type",
        "price_value",
        "currency_code",
        "unit_code",
        "effective_at",
        "source",
        "created_at",
    } <= set(table.columns.keys())


def test_gold_price_constraints_are_present() -> None:
    table = Base.metadata.tables["gold_prices"]
    constraints = {constraint.name for constraint in table.constraints}
    assert "ck_gold_prices_price_type" in constraints
    assert "ck_gold_prices_price_value_positive" in constraints
    assert "ck_gold_prices_source" in constraints
