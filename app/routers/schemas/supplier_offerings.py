from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SupplierCategoryOfferingCreate(BaseModel):
    category_id: UUID
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|PAUSED|STOPPED)$")
    is_preferred: bool = False
    supplier_category_name: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class SupplierCategoryOfferingUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(ACTIVE|PAUSED|STOPPED)$")
    is_preferred: bool | None = None
    supplier_category_name: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class SupplierCategoryOfferingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    supplier_id: UUID
    category_id: UUID
    status: str
    is_preferred: bool
    supplier_category_name: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class SupplierProductOfferingCreate(BaseModel):
    product_id: UUID
    supplier_product_code: str | None = Field(default=None, max_length=80)
    quoted_unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency_code: str = Field(default="TWD", pattern="^[A-Za-z]{3}$")
    min_order_quantity: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    lead_time_days: int | None = Field(default=None, ge=0)
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|PAUSED|STOPPED)$")
    is_preferred: bool = False
    note: str | None = Field(default=None, max_length=500)


class SupplierProductOfferingUpdate(BaseModel):
    supplier_product_code: str | None = Field(default=None, max_length=80)
    quoted_unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency_code: str | None = Field(default=None, pattern="^[A-Za-z]{3}$")
    min_order_quantity: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    lead_time_days: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern="^(ACTIVE|PAUSED|STOPPED)$")
    is_preferred: bool | None = None
    note: str | None = Field(default=None, max_length=500)


class SupplierProductOfferingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    supplier_id: UUID
    product_id: UUID
    supplier_product_code: str | None
    quoted_unit_cost: Decimal | None
    currency_code: str
    min_order_quantity: Decimal | None
    lead_time_days: int | None
    status: str
    is_preferred: bool
    note: str | None
    last_quoted_at: datetime | None
    created_at: datetime
    updated_at: datetime
