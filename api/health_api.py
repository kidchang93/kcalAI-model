from datetime import date, datetime

from timeutil import UTC

from fastapi import APIRouter, Query, status

from api.dependencies import DB, CurrentUser
from schemas.common_schema import ErrorResponse, MessageResponse
from schemas.health_schema import (
    GoalResponse,
    GoalUpsertRequest,
    MealCreateRequest,
    MealResponse,
    MedicalReportResponse,
    ProfileResponse,
    ProfileUpsertRequest,
    SummaryResponse,
    TrendsResponse,
    WeightCreateRequest,
    WeightResponse,
)
from services import health_service, medical_report_service

router = APIRouter()


# ---- 프로필 ----

@router.get(
    "/me/profile",
    response_model=ProfileResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_profile(current_user: CurrentUser, db: DB):
    profile = health_service.get_profile(db, current_user.id)

    # BMI·활동 권고는 저장하지 않고 여기서 계산해 싣는다 (docs/ACTIVITY_GUIDANCE.md 3-1).
    return health_service.build_profile_response(profile)


@router.put(
    "/me/profile",
    response_model=ProfileResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def update_profile(request: ProfileUpsertRequest, current_user: CurrentUser, db: DB):
    """400 은 **연령 제한**이다 (만 14세 미만, `docs/LEGAL_COMPLIANCE.md` §1)."""
    profile = health_service.upsert_profile(db, current_user.id, **request.model_dump())
    # 수정 직후에도 갱신된 BMI 를 함께 준다 — 앱이 다시 조회하지 않아도 되게.
    return health_service.build_profile_response(profile)


# ---- 목표 ----

@router.get(
    "/me/goal",
    response_model=GoalResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_goal(current_user: CurrentUser, db: DB):
    return health_service.get_goal(db, current_user.id)


@router.put(
    "/me/goal",
    response_model=GoalResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def update_goal(request: GoalUpsertRequest, current_user: CurrentUser, db: DB):
    return health_service.upsert_goal(db, current_user.id, **request.model_dump())


# ---- 홈 진행률 요약 ----

@router.get(
    "/me/summary",
    response_model=SummaryResponse,
    responses={401: {"model": ErrorResponse}},
)
def read_summary(
    current_user: CurrentUser,
    db: DB,
    target_date: date | None = Query(default=None, alias="date"),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    return health_service.get_summary(db, current_user.id, resolved_date)


# ---- 주/월 추이 ----

@router.get(
    "/me/trends",
    response_model=TrendsResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def read_trends(
    current_user: CurrentUser,
    db: DB,
    start_date: date = Query(...),
    end_date: date = Query(...),
):
    return health_service.get_trends(db, current_user.id, start_date, end_date)


# ---- 진료 지참용 리포트 ----

@router.get(
    "/me/report",
    response_model=MedicalReportResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def read_medical_report(
    current_user: CurrentUser,
    db: DB,
    start_date: date = Query(...),
    end_date: date = Query(...),
):
    """진료·영양상담에 가져갈 기간 기록.

    질환·병기 → 축별 추이 → 끼니 상세 순서다. 수치보다 기준이 먼저 와야 읽는 사람이
    맥락을 안다 (`services/medical_report_service.py`).
    """
    return medical_report_service.build_report(db, current_user.id, start_date, end_date)


# ---- 끼니 ----

@router.post(
    "/meals",
    response_model=MealResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}},
)
def create_meal(request: MealCreateRequest, current_user: CurrentUser, db: DB):
    return health_service.create_meal(db, current_user.id, **request.model_dump())


@router.get(
    "/meals",
    response_model=list[MealResponse],
    responses={401: {"model": ErrorResponse}},
)
def list_meals(
    current_user: CurrentUser,
    db: DB,
    target_date: date | None = Query(default=None, alias="date"),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    return health_service.list_meals(db, current_user.id, resolved_date)


@router.put(
    "/meals/{meal_id}",
    response_model=MealResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_meal(meal_id: int, request: MealCreateRequest, current_user: CurrentUser, db: DB):
    # 전체 교체 (PUT /api/pets/{id} 와 같은 방식). 항목은 지우고 다시 넣으며 total_kcal 은 서버가 재계산한다.
    # 단 logged_at 은 not-null 컬럼이므로 생략(null) 시 기존 기록 시각을 유지한다.
    return health_service.update_meal(db, current_user.id, meal_id, **request.model_dump())


@router.delete(
    "/meals/{meal_id}",
    response_model=MessageResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_meal(meal_id: int, current_user: CurrentUser, db: DB):
    health_service.soft_delete_meal(db, current_user.id, meal_id)
    return {"message": "끼니 기록을 삭제했습니다."}


# ---- 체중 ----

@router.post(
    "/weights",
    response_model=WeightResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}},
)
def create_weight(request: WeightCreateRequest, current_user: CurrentUser, db: DB):
    return health_service.create_weight(db, current_user.id, **request.model_dump())


@router.get(
    "/weights",
    response_model=list[WeightResponse],
    responses={401: {"model": ErrorResponse}},
)
def list_weights(current_user: CurrentUser, db: DB):
    return health_service.list_weights(db, current_user.id)
