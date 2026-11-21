from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SaleReturnCreate(BaseModel):
    return_no: str = Field(min_length=1, max_length=40)
    sale_line_ids: list[UUID] = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)


class SaleReturnLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    return_id: UUID
    sale_line_id: UUID
    product_id: UUID | None
    source_location_id: UUID | None
    product_code_snapshot: str | None
    barcode_snapshot: str | None
    product_name_snapshot: str
    net_weight: Decimal
    weight_unit_code: str
    settlement_reversal_amount: Decimal
    created_at: datetime


class SaleReturnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    sale_id: UUID
    return_no: str
    settlement_reversal_amount: Decimal
    currency_code: str
    reason: str | None
    note: str | None
    created_at: datetime
    lines: list[SaleReturnLineRead]
