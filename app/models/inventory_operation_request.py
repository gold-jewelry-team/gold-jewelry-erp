"""Durable registry for retry-safe inventory write requests."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InventoryOperationRequest(Base):
    """Immutable request identity and payload linked to its resulting movement."""

    __tablename__ = "inventory_operation_requests"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "idempotency_key",
            name="uq_inventory_operation_requests_company_key",
        ),
        CheckConstraint(
            "operation_type IN ('MANUAL_ADJUSTMENT', 'MANUAL_TRANSFER')",
            name="ck_inventory_operation_requests_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED')",
            name="ck_inventory_operation_requests_status",
        ),
        CheckConstraint(
            "(status = 'COMPLETED' AND movement_id IS NOT NULL) OR "
            "(status <> 'COMPLETED' AND movement_id IS NULL)",
            name="ck_inventory_operation_requests_completed_movement",
        ),
        Index(
            "ix_inventory_operation_requests_company_site_status_created",
            "company_id", "site_id", "status", "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    movement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_movements.id", ondelete="RESTRICT"), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
