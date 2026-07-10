from pydantic import BaseModel


class OptionItem(BaseModel):
    code: str
    label: str


class MetaOptionsResponse(BaseModel):
    conditions: list[OptionItem]
    allergens: list[OptionItem]


class MetaError(BaseModel):
    detail: str
