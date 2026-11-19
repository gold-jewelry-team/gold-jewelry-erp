from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCodeSequenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    next_number: int
    number_width: int
    updated_at: datetime


class ProductCodeSequenceUpdate(BaseModel):
    next_number: int | None = Field(default=None, ge=1)
    number_width: int | None = Field(default=None, ge=1, le=12)

    @field_validator("next_number", "number_width", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("流水號設定不可為空值。")
        return value


class ProductCodeGenerate(BaseModel):
    prefix: str = Field(min_length=2, max_length=21, pattern=r"^[A-Za-z0-9]{1,20}-$")


class ProductCodeGenerated(BaseModel):
    product_code: str
    next_number: int
