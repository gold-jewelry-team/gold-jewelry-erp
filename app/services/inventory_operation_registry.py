"""Durable registry orchestration for manual inventory operations.

PENDING is committed before touching the inventory ledger. The movement insert and
COMPLETED transition are then committed together in the caller's transaction.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import InventoryMovement
from app.models.inventory_operation_request import InventoryOperationRequest
from app.services.inventory_operation_requests import fingerprint_inventory_operation


class InventoryOperationRequestConflict(ValueError):
    """An idempotency key is already bound to another or unfinished operation."""


def prepare_inventory_operation_request(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    operation_type: str,
    idempotency_key: UUID,
    payload: dict,
    legacy_movement_lookup,
) -> tuple[InventoryOperationRequest, InventoryMovement | None, bool]:
    """Load an existing request or durably register a new PENDING request.

    legacy_movement_lookup must apply the pre-registry ledger's exact matching
    rules and return its movement, or None. It must never guess from similar rows.
    """
    canonical, fingerprint = fingerprint_inventory_operation(
        operation_type=operation_type,
        company_id=company_id,
        site_id=site_id,
        payload=payload,
    )

    def load_winner():
        return session.scalar(
            select(InventoryOperationRequest)
            .where(
                InventoryOperationRequest.company_id == company_id,
                InventoryOperationRequest.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )

    existing = load_winner()
    if existing is not None:
        return _resolve_existing(session, existing, operation_type, site_id, canonical, fingerprint)

    # Preserve compatibility with movements written before the registry existed.
    legacy_movement = legacy_movement_lookup()
    row = InventoryOperationRequest(
        company_id=company_id,
        site_id=site_id,
        idempotency_key=idempotency_key,
        operation_type=operation_type,
        payload=canonical,
        payload_fingerprint=fingerprint,
        status="COMPLETED" if legacy_movement is not None else "PENDING",
        movement_id=legacy_movement.id if legacy_movement is not None else None,
        completed_at=datetime.now(timezone.utc) if legacy_movement is not None else None,
    )
    session.add(row)
    try:
        # A durable PENDING marker survives a process crash before ledger write.
        # For a legacy match, this commits only the registry link to the old row.
        session.commit()
        session.refresh(row)
    except IntegrityError:
        # A concurrent request may have won the unique company/key race.
        # Roll back the failed transaction before loading and comparing its row.
        session.rollback()
        winner = load_winner()
        if winner is None:
            raise
        return _resolve_existing(session, winner, operation_type, site_id, canonical, fingerprint)

    if legacy_movement is not None:
        movement = session.get(InventoryMovement, legacy_movement.id)
        return row, movement, True
    return row, None, False


def _resolve_existing(session, row, operation_type, site_id, canonical, fingerprint):
    if (
        row.operation_type != operation_type
        or row.site_id != site_id
        or row.payload != canonical
        or row.payload_fingerprint != fingerprint
    ):
        raise InventoryOperationRequestConflict(
            "此冪等識別碼已綁定不同的庫存操作內容，請先核對原始異動。"
        )
    if row.status == "COMPLETED":
        movement = session.get(InventoryMovement, row.movement_id)
        if movement is None:
            raise InventoryOperationRequestConflict(
                "操作登記已完成但找不到關聯庫存異動，請停止重試並人工檢查。"
            )
        return row, movement, True
    if row.status == "PENDING":
        raise InventoryOperationRequestConflict(
            "此庫存操作仍處於待核對狀態；系統不會自動重送，請先從操作恢復清單核對。"
        )
    raise InventoryOperationRequestConflict(
        "此庫存操作曾失敗並保留紀錄；請先核對原因，再使用明確的人工恢復流程。"
    )


def mark_inventory_operation_failed(
    session: Session, *, request_id: UUID, failure_code: str, failure_message: str
) -> None:
    """Record a sanitized, deterministic business failure after rolling back work."""
    session.rollback()
    row = session.get(InventoryOperationRequest, request_id)
    if row is None or row.status != "PENDING":
        return
    row.status = "FAILED"
    row.failure_code = failure_code[:60]
    row.failure_message = failure_message[:300]
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
