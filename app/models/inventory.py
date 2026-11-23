"""Append-only inventory movement ledger."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Uuid, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InventoryMovement(Base):
    """A movement changes a product's position; balances are derived from this ledger."""
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('RECEIPT', 'SALE', 'TRANSFER', 'ADJUSTMENT', 'RETURN', 'REPAIR_SEND', 'REPAIR_RETURN')",
            name="ck_inventory_movements_type",
        ),
        CheckConstraint("quantity > 0", name="ck_inventory_movements_quantity_positive"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_inventory_movements_weight_nonnegative"),
        CheckConstraint(
            "(from_location_id IS NOT NULL OR to_location_id IS NOT NULL) "
            "AND (from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id)",
            name="ck_inventory_movements_locations",
        ),
        CheckConstraint(
            "(movement_type = 'TRANSFER' AND from_location_id IS NOT NULL AND to_location_id IS NOT NULL) "
            "OR (movement_type <> 'TRANSFER')",
            name="ck_inventory_movements_transfer_locations",
        ),
        Index("ix_inventory_movements_company_product_time", "company_id", "product_id", "occurred_at"),
        Index("ix_inventory_movements_from_location", "from_location_id", "occurred_at"),
        Index("ix_inventory_movements_to_location", "to_location_id", "occurred_at"),
        Index(
            "uq_inventory_movements_company_idempotency_key",
            "company_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("storage_locations.id", ondelete="RESTRICT"), nullable=True)
    to_location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("storage_locations.id", ondelete="RESTRICT"), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=Decimal("1"))
    weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    weight_unit_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
