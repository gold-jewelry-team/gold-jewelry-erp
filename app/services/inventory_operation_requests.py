"""Canonical request payload helpers for durable inventory idempotency."""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID


SUPPORTED_OPERATION_TYPES = {"MANUAL_ADJUSTMENT", "MANUAL_TRANSFER"}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value).lower()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported inventory request payload value: {type(value).__name__}")


def canonical_inventory_operation_payload(
    *, operation_type: str, company_id: UUID, site_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Return deterministic semantic payload; callers must pass validated/defaulted fields."""
    if operation_type not in SUPPORTED_OPERATION_TYPES:
        raise ValueError("Unsupported inventory operation type.")
    semantic_payload = {
        "operation_type": operation_type,
        "company_id": company_id,
        "site_id": site_id,
        "payload": payload,
    }
    return _canonical_value(semantic_payload)


def fingerprint_inventory_operation(
    *, operation_type: str, company_id: UUID, site_id: UUID, payload: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    canonical = canonical_inventory_operation_payload(
        operation_type=operation_type,
        company_id=company_id,
        site_id=site_id,
        payload=payload,
    )
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return canonical, hashlib.sha256(encoded).hexdigest()
