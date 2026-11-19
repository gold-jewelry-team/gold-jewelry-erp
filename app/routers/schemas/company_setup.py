from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    tax_id: str | None = Field(default=None, max_length=20)


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    tax_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SiteCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)


class SiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    address: str | None
    phone: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StorageLocationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    location_type: str = Field(default="OTHER", pattern="^(STORE_FLOOR|SAFE|WAREHOUSE|REPAIR|TRANSIT|OTHER)$")
    description: str | None = Field(default=None, max_length=255)


class StorageLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    site_id: UUID
    code: str
    name: str
    location_type: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
