from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ProductCodeSequenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    next_number: int
    number_width: int
    updated_at: datetime


class ProductCodeSequenceUpdate(BaseModel):
    next_number: int | None = Field(default=None, ge=1)
    number_width: int | None = Field(default=None, ge=1, le=12)


class ProductCodeGenerate(BaseModel):
    prefix: str = Field(min_length=2, max_length=21, pattern=r"^[A-Za-z0-9]{1,20}-$")


class ProductCodeGenerated(BaseModel):
    product_code: str
    next_number: int
