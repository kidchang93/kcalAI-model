from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Sex = Literal["male", "female"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
GoalType = Literal["loss", "maintain", "gain"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]
ItemSource = Literal["ai", "manual"]


class ProfileUpsertRequest(BaseModel):
    sex: Sex
    birth_year: int = Field(..., ge=1900, le=2100)
    height_cm: float = Field(..., gt=0, le=300)
    weight_kg: float = Field(..., gt=0, le=500)
    activity_level: ActivityLevel


class ProfileResponse(BaseModel):
    id: int
    user_id: int
    sex: str
    birth_year: int
    height_cm: float
    weight_kg: float
    activity_level: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GoalUpsertRequest(BaseModel):
    goal_type: GoalType
    # 미지정 시 Mifflin-St Jeor 로 자동 산출한다.
    target_kcal: int | None = Field(default=None, ge=0, le=20000)
    target_weight_kg: float | None = Field(default=None, gt=0, le=500)


class GoalResponse(BaseModel):
    id: int
    user_id: int
    goal_type: str
    target_kcal: int
    target_weight_kg: float | None
    started_at: datetime
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class MealBreakdown(BaseModel):
    breakfast: int
    lunch: int
    dinner: int
    snack: int


class SummaryResponse(BaseModel):
    date: str
    # 열린 목표가 없으면 null. 0 이 아니다 (0 이면 앱이 "목표 설정" CTA 를 못 띄우고 진행률이 0 으로 나뉜다).
    target_kcal: int | None
    consumed_kcal: int
    remaining_kcal: int | None
    meals: MealBreakdown


class MealItemInput(BaseModel):
    food_label: str = Field(..., min_length=1, max_length=100)
    serving_ratio: float = Field(..., gt=0, le=99)
    kcal: int = Field(..., ge=0, le=100000)
    source: ItemSource
    confidence: float | None = Field(default=None, ge=0, le=1)


class MealCreateRequest(BaseModel):
    meal_type: MealType
    logged_at: datetime | None = None
    photo_s3_key: str | None = Field(default=None, max_length=255)
    items: list[MealItemInput] = Field(..., min_length=1)


class MealItemResponse(BaseModel):
    id: int
    food_label: str
    serving_ratio: float
    kcal: int
    source: str
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MealResponse(BaseModel):
    id: int
    user_id: int
    meal_type: str
    logged_at: datetime
    photo_s3_key: str | None
    total_kcal: int
    deleted_at: datetime | None
    created_at: datetime
    items: list[MealItemResponse]

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str


class WeightCreateRequest(BaseModel):
    weight_kg: float = Field(..., gt=0, le=500)
    measured_at: datetime | None = None


class WeightResponse(BaseModel):
    id: int
    user_id: int
    weight_kg: float
    measured_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthError(BaseModel):
    detail: str
