from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Species = Literal["dog", "cat", "other"]


class PetUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    species: Species
    breed: str | None = Field(default=None, max_length=50)
    birth_year: int | None = Field(default=None, ge=1980, le=2100)
    weight_kg: float | None = Field(default=None, gt=0, le=200)
    # 모름 허용.
    is_neutered: bool | None = None


class PetResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    species: str
    breed: str | None
    birth_year: int | None
    weight_kg: float | None
    is_neutered: bool | None
    # 권장 일일 칼로리(MER = RER × 종 계수). 응답 시 계산하며 저장하지 않는다.
    # 체중 없음·species=other 는 null (DATA_MODEL.md 18장).
    recommended_kcal: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FeedingCreateRequest(BaseModel):
    food_label: str = Field(..., min_length=1, max_length=100)
    amount_g: float = Field(..., gt=0, le=99999)
    # MVP 는 급여량(g)만 필수. 칼로리 산출(RER/MER)은 다음 단계다.
    kcal: int | None = Field(default=None, ge=0, le=100000)
    fed_at: datetime | None = None


class FeedingResponse(BaseModel):
    id: int
    pet_id: int
    fed_at: datetime
    food_label: str
    amount_g: float
    kcal: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str


class PetError(BaseModel):
    detail: str
