from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LaborCodeMapItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    digit: int = Field(ge=0, le=9)
    code_char: str = Field(min_length=1, max_length=10)


class LaborCodeConfigUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    prefix: str = Field(min_length=1, max_length=5, pattern=r"^[A-Za-z0-9]{1,5}$")
    mappings: list[LaborCodeMapItem] = Field(default_factory=list, max_length=10)


class LaborCodeConfigRead(BaseModel):
    company_id: UUID
    prefix: str
    mappings: list[LaborCodeMapItem]
