from app.db.base import Base
from app import models  # noqa: F401


def test_core_location_tables_are_registered() -> None:
    assert {"companies", "sites", "storage_locations"} <= set(Base.metadata.tables)


def test_storage_location_codes_are_unique_per_site() -> None:
    table = Base.metadata.tables["storage_locations"]
    constraints = {constraint.name for constraint in table.constraints}
    assert "uq_storage_locations_site_code" in constraints
