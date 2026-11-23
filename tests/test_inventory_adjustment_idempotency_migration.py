from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base


def test_inventory_adjustment_idempotency_index_is_unique_and_partial():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("inventory_movements")}
        assert "idempotency_key" in columns

        indexes = inspector.get_indexes("inventory_movements")
        unique = next(
            index for index in indexes
            if index["name"] == "uq_inventory_movements_company_idempotency_key"
        )
        assert unique["unique"] is True
        assert unique["column_names"] == ["company_id", "idempotency_key"]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
