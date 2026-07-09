from datetime import datetime

from pydantic import BaseModel, Field


class NutritionEstimateRequest(BaseModel):
    food_label: str = Field(..., min_length=1, max_length=100)


class NutritionEstimateResponse(BaseModel):
    food_label: str
    kcal_per_serving: int
    serving_desc: str
    carbs_g: float | None
    protein_g: float | None
    fat_g: float | None
    source: str
    created_at: datetime
    # 캐시에서 나왔는지 여부. false 면 LLM 을 새로 태운 것이다.
    cached: bool

    model_config = {"from_attributes": True}


class NutritionError(BaseModel):
    detail: str
