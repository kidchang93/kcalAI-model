from datetime import datetime
from typing import Annotated, Literal

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


class NutritionWarningsRequest(BaseModel):
    # 1~10개, 중복 허용 — 서버가 dedupe 한다. 라벨은 각 1~100자 (DATA_MODEL.md 16장).
    food_labels: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        ..., min_length=1, max_length=10
    )


class NutritionWarningItem(BaseModel):
    source: Literal["condition", "allergy"]
    # condition_types.code 또는 allergen_types.code
    code: str
    label: str
    # 걸린 키워드 원문 1개만 노출한다 — 전체 사전은 비노출 (16장).
    matched_keyword: str
    matched_label: str


class NutritionWarningsResponse(BaseModel):
    warnings: list[NutritionWarningItem]


class NutritionError(BaseModel):
    detail: str
