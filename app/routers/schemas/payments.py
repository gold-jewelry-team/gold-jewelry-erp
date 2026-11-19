from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    payment_method: str = Field(pattern="^(CASH|CARD|TRANSFER|OTHER)$")
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    sale_id: UUID | None
    sale_return_id: UUID | None
    direction: str
    payment_method: str
    amount: Decimal
    currency_code: str
    reference_no: str | None
    paid_at: datetime
    note: str | None
    created_at: datetime
