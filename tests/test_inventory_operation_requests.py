from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.models.inventory_operation_request import InventoryOperationRequest
from app.services.inventory_operation_requests import fingerprint_inventory_operation


COMPANY_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SITE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def test_inventory_operation_fingerprint_is_stable_for_equivalent_values():
    first_payload = {
        "product_id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        "quantity": Decimal("1.000"),
        "occurred_at": datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc),
        "note": "manual adjustment",
    }
    second_payload = {
        "note": "manual adjustment",
        "occurred_at": datetime(2026, 11, 25, 9, 0, tzinfo=timezone(timedelta(hours=8))),
        "quantity": Decimal("1.000"),
        "product_id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
    }

    canonical_a, fingerprint_a = fingerprint_inventory_operation(
        operation_type="MANUAL_ADJUSTMENT",
        company_id=COMPANY_ID,
        site_id=SITE_ID,
        payload=first_payload,
    )
    canonical_b, fingerprint_b = fingerprint_inventory_operation(
        operation_type="MANUAL_ADJUSTMENT",
        company_id=COMPANY_ID,
        site_id=SITE_ID,
        payload=second_payload,
    )

    assert canonical_a == canonical_b
    assert fingerprint_a == fingerprint_b
    assert len(fingerprint_a) == 64


def test_inventory_operation_fingerprint_changes_when_semantics_change():
    common = {
        "product_id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        "quantity": Decimal("1"),
        "note": "manual adjustment",
    }
    _, original = fingerprint_inventory_operation(
        operation_type="MANUAL_ADJUSTMENT",
        company_id=COMPANY_ID,
        site_id=SITE_ID,
        payload=common,
    )
    _, changed = fingerprint_inventory_operation(
        operation_type="MANUAL_TRANSFER",
        company_id=COMPANY_ID,
        site_id=SITE_ID,
        payload=common,
    )
    assert original != changed


def test_inventory_operation_fingerprint_rejects_unknown_operation_type():
    with pytest.raises(ValueError, match="Unsupported inventory operation"):
        fingerprint_inventory_operation(
            operation_type="STOCKTAKE",
            company_id=COMPANY_ID,
            site_id=SITE_ID,
            payload={"quantity": Decimal("1")},
        )


def test_inventory_operation_request_model_has_company_key_uniqueness():
    constraints = {
        constraint.name for constraint in InventoryOperationRequest.__table__.constraints
    }
    assert "uq_inventory_operation_requests_company_key" in constraints
    assert "ck_inventory_operation_requests_status" in constraints
    assert "ck_inventory_operation_requests_completed_movement" in constraints
