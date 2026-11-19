from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GoldPriceCreate(BaseModel):
    site_id: UUID | None = None
    price_type: str = Field(pattern="^(BUY|SELL)$")
    price_value: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    currency_code: str = Field(default="TWD", min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    unit_code: str = Field(min_length=1, max_length=20)
    effective_at: datetime
    source: str = Field(default="MANUAL", pattern="^(MANUAL|IMPORT|SYSTEM)$")
    note: str | None = Field(default=None, max_length=500)


class GoldPriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    site_id: UUID | None
    price_type: str
    price_value: Decimal
    currency_code: str
    unit_code: str
    effective_at: datetime
    source: str
    note: str | None
    created_at: datetime
