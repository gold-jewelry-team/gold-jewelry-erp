from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    tax_id: str | None = Field(default=None, max_length=20)
    contact_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=500)


class SupplierUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    tax_id: str | None = Field(default=None, max_length=20)
    contact_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    tax_id: str | None
    contact_name: str | None
    phone: str | None
    address: str | None
    note: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PurchaseLineCreate(BaseModel):
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    weight_unit_code: str | None = Field(default=None, max_length=20)
    unit_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    cost_labor_fee: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)


class PurchaseCreate(BaseModel):
    site_id: UUID
    supplier_id: UUID
    purchase_no: str = Field(min_length=1, max_length=50)
    order_date: date
    expected_date: date | None = None
    currency_code: str = Field(default="TWD", min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    note: str | None = Field(default=None, max_length=500)
    lines: list[PurchaseLineCreate] = Field(min_length=1, max_length=500)


class PurchaseLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    purchase_id: UUID
    product_id: UUID
    quantity: Decimal
    received_quantity: Decimal
    weight: Decimal | None
    weight_unit_code: str | None
    unit_cost: Decimal
    cost_labor_fee: Decimal
    note: str | None
    created_at: datetime


class PurchaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    supplier_id: UUID
    purchase_no: str
    order_date: date
    expected_date: date | None
    status: str
    currency_code: str
    note: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseLineRead]


class PurchaseReceive(BaseModel):
    purchase_line_id: UUID
    location_id: UUID
    received_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    idempotency_key: UUID


class PurchaseActionResult(BaseModel):
    purchase_id: UUID
    status: str
    message: str
