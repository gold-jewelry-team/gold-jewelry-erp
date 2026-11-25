from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InventoryAdjustmentCreate(BaseModel):
    site_id: UUID
    product_id: UUID
    location_id: UUID
    direction: str = Field(pattern="^(IN|OUT)$")
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    weight_unit_code: str | None = Field(default=None, max_length=20)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: UUID


class InventoryTransferCreate(BaseModel):
    site_id: UUID
    product_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    weight_unit_code: str | None = Field(default=None, max_length=20)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: UUID


class InventoryMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    product_id: UUID
    movement_type: str
    from_location_id: UUID | None
    to_location_id: UUID | None
    quantity: Decimal
    weight: Decimal | None
    weight_unit_code: str | None
    reference_type: str | None
    reference_id: UUID | None
    occurred_at: datetime
    note: str | None
    created_at: datetime


class StockBalanceRead(BaseModel):
    company_id: UUID
    site_id: UUID
    site_name: str
    product_id: UUID
    product_code: str
    barcode: str | None
    product_name: str
    location_id: UUID
    location_code: str
    location_name: str
    quantity: Decimal


class StocktakeAdjustmentItem(BaseModel):
    product_id: UUID
    location_id: UUID
    expected_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    actual_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    expected_net_weight: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    idempotency_key: UUID
    note: str | None = Field(default=None, max_length=500)


class StocktakeAdjustmentBatchCreate(BaseModel):
    site_id: UUID
    items: list[StocktakeAdjustmentItem] = Field(min_length=1, max_length=500)


class StocktakeAdjustmentBatchRead(BaseModel):
    applied_count: int
    adjustment_count: int
    no_change_count: int
    replayed: bool
    movements: list[InventoryMovementRead]


class InventoryOperationRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    idempotency_key: UUID
    operation_type: str
    payload: dict
    payload_fingerprint: str
    status: str
    movement_id: UUID | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
