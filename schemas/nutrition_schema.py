from datetime import datetime

from pydantic import BaseModel, Field


class NutritionEstimateRequest(BaseModel):
    food_label: str = Field(..., min_length=1, max_length=100)


class NutritionEstimateResponse(BaseModel):
    # 매칭된 DB 행의 이름 — 유사도 매칭이면 요청 라벨과 다를 수 있다 (13장).
    food_label: str
    kcal_per_serving: int
    serving_desc: str
    carbs_g: float | None
    protein_g: float | None
    fat_g: float | None
    source: str
    created_at: datetime
    # 응답 계약 유지용 — 항상 DB 조회이므로 항상 true 다 (13장, LLM 없음).
    cached: bool

    model_config = {"from_attributes": True}


class NutritionError(BaseModel):
    detail: str
