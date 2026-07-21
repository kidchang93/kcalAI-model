from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# 운동 기록 계약 (docs/ACTIVITY_GUIDANCE.md 3-2).
# 앱과 웹이 같은 레벨의 서비스라 이 API 는 **플랫폼 중립**이다 — 기기 연동은 나중에 source 가
# 하나 늘 뿐이고, 기록·조회·집계 경로는 그대로다.

# 강도 축은 보건복지부 지침과 일치시킨다. 권장량 집계는 중강도·고강도만 센다.
Intensity = Literal["light", "moderate", "vigorous"]

# 입력 경로. 지금은 manual 만 쓰이고, 3단계에서 기기 값이 같은 테이블에 들어온다.
ExerciseSource = Literal["manual", "healthkit", "health_connect"]


class ExerciseCreateRequest(BaseModel):
    # exercise_type 은 참조 테이블이 아니라 fitness_rules.EXERCISE_TYPES 의 키다 —
    # MET 값이 코드에 있어야 하므로 목록도 같은 곳에 둔다. 검증은 서비스가 한다.
    exercise_type: str = Field(..., min_length=1, max_length=30)
    duration_minutes: int = Field(..., ge=1, le=1440)
    # 생략 시 종류별 기본 강도를 쓴다 (걷기=중강도, 달리기=고강도 …).
    intensity: Intensity | None = None
    # 생략 시 서버가 MET × 체중 × 시간으로 산출한다. 체중을 모르면 null 로 남는다.
    kcal: int | None = Field(default=None, ge=0, le=20000)
    # 미지정 시 서버가 현재 시각(UTC). 과거 날짜는 그 날의 UTC 정오로 앵커해 보낸다(끼니와 같은 규약).
    performed_at: datetime | None = None
    memo: str | None = Field(default=None, max_length=200)


class ExerciseUpdateRequest(ExerciseCreateRequest):
    """전체 교체 수정. 끼니 PUT 과 같은 방식이다."""


class ExerciseResponse(BaseModel):
    id: int
    exercise_type: str
    # 한국어 표시명 — 앱이 코드→라벨 표를 따로 갖지 않게 서버가 준다.
    exercise_type_label: str
    duration_minutes: int
    intensity: Intensity
    kcal: int | None
    source: ExerciseSource
    memo: str | None
    performed_at: datetime

    model_config = {"from_attributes": True}


class ExerciseListResponse(BaseModel):
    exercises: list[ExerciseResponse]


class ExerciseTypeOption(BaseModel):
    """앱의 운동 종류 선택지. MET 는 노출하지 않는다 — 산출은 서버 책임이다."""

    code: str
    label: str
    default_intensity: Intensity


class ExerciseSummaryResponse(BaseModel):
    start_date: date
    end_date: date
    # 강도별 합계 (저강도는 권장량에 포함되지 않지만 기록은 보여준다).
    light_minutes: int
    moderate_minutes: int
    vigorous_minutes: int
    # 고강도 1분 = 중강도 2분(KPAG)으로 환산한 합계. 권장 하한과 대조하는 단일 축이다.
    equivalent_moderate_minutes: int
    # 근력운동은 분이 아니라 '주 몇 일'로 센다 — 지침이 그렇게 권고한다.
    strength_days: int
    total_kcal: int
    exercise_count: int
    # 권장 하한(주 150분) 대비. 달성했으면 remaining 은 0 이다.
    recommended_min_minutes: int
    remaining_minutes: int
    achieved: bool
    notice: str


class ExerciseError(BaseModel):
    detail: str
