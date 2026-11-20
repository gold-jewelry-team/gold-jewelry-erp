from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GoldMaterialAllocationCreate(BaseModel):
    bill_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class GoldMaterialMovementCreate(BaseModel):
    site_id: UUID
    supplier_id: UUID | None = None
    purchase_id: UUID | None = None
    movement_no: str = Field(min_length=1, max_length=50)
    movement_type: str = Field(pattern="^(OPENING|RECEIPT|ADJUSTMENT_IN|ADJUSTMENT_OUT|SUPPLIER_DELIVERY)$")
    source_type: str | None = Field(default=None, max_length=30)
    purity_label: str = Field(min_length=1, max_length=30)
    purity_ratio: Decimal = Field(gt=0, le=1, max_digits=8, decimal_places=6)
    gross_weight: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    loss_weight: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    weight_unit_code: str = Field(pattern="^(G|QIAN|LIANG)$")
    gold_price_value: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    gold_price_unit_code: str = Field(pattern="^(G|QIAN|LIANG)$")
    deduction_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    allocations: list[GoldMaterialAllocationCreate] = Field(default_factory=list, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class GoldMaterialAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    movement_id: UUID
    bill_id: UUID
    amount: Decimal
    created_at: datetime


class GoldMaterialMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    supplier_id: UUID | None
    purchase_id: UUID | None
    movement_no: str
    movement_type: str
    source_type: str | None
    purity_label: str
    purity_ratio: Decimal
    gross_weight: Decimal
    loss_weight: Decimal
    net_weight: Decimal
    weight_unit_code: str
    fine_gold_weight_g: Decimal
    gold_price_value: Decimal
    gold_price_unit_code: str
    deduction_amount: Decimal
    valuation_amount: Decimal
    note: str | None
    occurred_at: datetime
    created_at: datetime
    allocations: list[GoldMaterialAllocationRead]


class GoldMaterialBalanceRead(BaseModel):
    company_id: UUID
    site_id: UUID
    fine_gold_weight_g: Decimal
