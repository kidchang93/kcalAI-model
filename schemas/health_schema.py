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


class ActivityGuide(BaseModel):
    """주당 권장 신체활동량 (보건복지부 2023). 개인 처방이 아니라 연령대별 일반 권고다."""

    moderate_min_minutes: int
    moderate_max_minutes: int
    vigorous_min_minutes: int
    # 노인은 고강도 상한이 성인보다 낮다 (150 → 100분).
    vigorous_max_minutes: int
    strength_days: int
    # 평형성 운동은 65세 이상에만 있는 축이다 — 성인은 None.
    balance_days: int | None
    is_senior: bool
    tips: list[str]
    source: str
    notice: str


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
    # 아래 네 필드는 **저장하지 않고 응답 시 계산**한다 (docs/ACTIVITY_GUIDANCE.md 3-1).
    # 키·체중이 바뀌면 즉시 따라와야 하고, 저장하면 두 값이 어긋난다 (펫 recommended_kcal 선례).
    # 대한비만학회 2022 기준(한국인)이라 WHO 국제 기준과 다르다.
    bmi: float | None = None
    bmi_category: str | None = None
    bmi_category_label: str | None = None
    # BMI 가 근육량을 구분하지 못한다는 한계 고지. 앱은 이 문구를 그대로 쓴다(하드코딩 금지).
    bmi_notice: str | None = None
    activity_guide: ActivityGuide | None = None

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


class DayNutrientAxis(BaseModel):
    # sodium / potassium / phosphorus
    nutrient: str
    label: str
    consumed_mg: float
    # 1일 상한. **나트륨에만 있다** — 칼륨·인은 지침이 혈청 수치 기반 개인화라 상한이 없다
    # (KDOQI 2020). null 이면 앱은 게이지 없이 수치만 그린다.
    limit_mg: int | None
    # 상한이 아니라 투석 환자에게 흔히 쓰이는 실무 참고치. **게이지로 쓰지 않는다.**
    reference_mg: int | None
    # 이 기준이 어디서 왔는지(질환·병기). 기준이 없으면 병기 입력 안내가 들어온다.
    basis: str | None
    # 이 축의 실측을 찾은 항목 수. total_items 보다 작으면 합계가 과소평가다 — 앱이 밝힌다.
    measured_items: int


class DayNutrients(BaseModel):
    axes: list[DayNutrientAxis]
    total_items: int
    notice: str


class SummaryResponse(BaseModel):
    date: str
    # 열린 목표가 없으면 null. 0 이 아니다 (0 이면 앱이 "목표 설정" CTA 를 못 띄우고 진행률이 0 으로 나뉜다).
    target_kcal: int | None
    consumed_kcal: int
    remaining_kcal: int | None
    meals: MealBreakdown
    # 질환 축 하루 누적. 해당 질환이 없으면 null (2026-07-23, DATA_MODEL 28장).
    nutrients: DayNutrients | None = None


class TrendDay(BaseModel):
    date: str
    consumed_kcal: int
    meal_count: int


class NutrientTrendDay(BaseModel):
    date: str
    consumed_mg: float
    # 이 축의 실측을 찾은 항목 수 / 그날 기록한 전체 항목 수. 앞이 작으면 합계가 과소평가다.
    measured_items: int
    total_items: int


class NutrientTrendAxis(BaseModel):
    nutrient: str
    label: str
    # 범위 내 모든 날짜를 오름차순으로 채운다 (기록 없는 날은 0).
    days: list[NutrientTrendDay]
    # **기록한 날만** 나눈 평균. 기록 없는 날을 0으로 넣으면 "적게 먹었다"로 읽힌다.
    # 기록이 하루도 없으면 null.
    average_mg: float | None
    recorded_days: int
    # 1일 상한 — 나트륨에만 있다 (DayNutrientAxis 와 같은 규칙).
    limit_mg: int | None
    # 상한이 있을 때만 셀 수 있다. 기록 없는 날은 넘었는지 알 수 없어 제외한다.
    days_over_limit: int | None
    reference_mg: int | None
    basis: str | None


class NutrientTrends(BaseModel):
    axes: list[NutrientTrendAxis]
    notice: str


class TrendsResponse(BaseModel):
    start_date: str
    end_date: str
    # 열린 목표가 없으면 null. 0 이 아니다 — summary 와 동일 규칙.
    target_kcal: int | None
    # 범위 내 모든 날짜를 오름차순으로 채운다. 기록 없는 날도 0 으로 존재한다 (그래프용).
    days: list[TrendDay]
    # 질환 축 기간 추이. 해당 질환이 없으면 null (2026-07-25, DATA_MODEL 28장).
    # 만성질환 관리에서 하루는 흔들리고 **추세가 말을 한다** — 리포트가 kcal 만 보여주면
    # 정작 이 앱의 대상 사용자에게 중요한 숫자가 어디에도 없다.
    nutrients: NutrientTrends | None = None


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


class MealUpdateRequest(MealCreateRequest):
    # 전체 교체 (PUT /api/pets/{id} 와 같은 방식). 항목은 지우고 다시 넣으며 total_kcal 은 서버가 재계산한다.
    # 단 logged_at 은 not-null 컬럼이므로 생략(null) 시 기존 기록 시각을 유지한다.
    pass


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
