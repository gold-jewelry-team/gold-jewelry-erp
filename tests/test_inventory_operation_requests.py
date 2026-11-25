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

def test_late_failure_marker_does_not_overwrite_completed_request():
    from app.services.inventory_operation_registry import mark_inventory_operation_failed

    engine, TestSession, ids = _context()
    try:
        key = uuid4()
        raw_payload = _transfer_payload(ids, key)
        validated = InventoryTransferCreate.model_validate(raw_payload)
        canonical, fingerprint = fingerprint_inventory_operation(
            operation_type="MANUAL_TRANSFER",
            company_id=ids["company_id"],
            site_id=ids["site_id"],
            payload=validated.model_dump(mode="python"),
        )
        with TestSession() as session:
            movement_id = session.scalar(select(InventoryMovement.id).where(
                InventoryMovement.company_id == ids["company_id"],
                InventoryMovement.movement_type == "RECEIPT",
            ))
            request = InventoryOperationRequest(
                company_id=ids["company_id"],
                site_id=ids["site_id"],
                idempotency_key=key,
                operation_type="MANUAL_TRANSFER",
                payload=canonical,
                payload_fingerprint=fingerprint,
                status="COMPLETED",
                movement_id=movement_id,
            )
            session.add(request)
            session.commit()
            request_id = request.id

        with TestSession() as session:
            mark_inventory_operation_failed(
                session,
                request_id=request_id,
                failure_code="VALIDATION_FAILED",
                failure_message="late validation failure",
            )

        with TestSession() as session:
            row = session.get(InventoryOperationRequest, request_id)
            assert row.status == "COMPLETED"
            assert row.failure_code is None
            assert row.failure_message is None
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

