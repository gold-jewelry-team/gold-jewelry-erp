from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductCategoryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None
    sort_order: int = 0


class ProductCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    parent_id: UUID | None
    code: str
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime


class ProductCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    category_id: UUID | None = None
    product_code: str = Field(min_length=1, max_length=50)
    barcode: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    material_code: str | None = Field(default=None, max_length=30)
    gross_weight: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    net_weight: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    weight_unit_code: str = Field(default="QIAN", min_length=1, max_length=20)
    labor_fee: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    chain_length: str | None = Field(default=None, max_length=40)
    style_code: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    category_id: UUID | None = None
    product_code: str | None = Field(default=None, min_length=1, max_length=50)
    barcode: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    material_code: str | None = Field(default=None, max_length=30)
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    weight_unit_code: str | None = Field(default=None, min_length=1, max_length=20)
    labor_fee: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    chain_length: str | None = Field(default=None, max_length=40)
    style_code: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    category_id: UUID | None
    product_code: str
    barcode: str | None
    name: str
    material_code: str | None
    gross_weight: Decimal
    net_weight: Decimal
    weight_unit_code: str
    labor_fee: Decimal
    chain_length: str | None
    style_code: str | None
    note: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductLabelDataRead(BaseModel):
    """Authoritative data assembled for a printable single-item label."""
    model_config = ConfigDict(from_attributes=True)
    product_id: UUID
    product_code: str
    barcode: str | None
    gross_weight: Decimal
    weight_unit_code: str
    selling_labor_fee: Decimal
    cost_labor_fee: Decimal | None
    chain_length: str | None
    style_code: str | None
    supplier_code: str | None
    supplier_name: str | None
    purchase_date: date | None
    locations: list[str]
