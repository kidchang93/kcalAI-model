import logging
from datetime import date, datetime

from timeutil import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from log_utils import setup_level_logger
from models.auth_model import User
from schemas.health_schema import (
    GoalResponse,
    GoalUpsertRequest,
    HealthError,
    MealCreateRequest,
    MealResponse,
    MealUpdateRequest,
    MessageResponse,
    ProfileResponse,
    ProfileUpsertRequest,
    SummaryResponse,
    TrendsResponse,
    WeightCreateRequest,
    WeightResponse,
)
from services import health_service

error_logger = setup_level_logger(logging.ERROR)

router = APIRouter()


# ---- 프로필 ----

@router.get(
    "/me/profile",
    response_model=ProfileResponse,
    responses={401: {"model": HealthError}, 404: {"model": HealthError}},
)
def read_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return health_service.get_profile(db, current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.put(
    "/me/profile",
    response_model=ProfileResponse,
    responses={401: {"model": HealthError}},
)
def update_profile(
    request: ProfileUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return health_service.upsert_profile(
        db,
        current_user.id,
        sex=request.sex,
        birth_year=request.birth_year,
        height_cm=request.height_cm,
        weight_kg=request.weight_kg,
        activity_level=request.activity_level,
    )


# ---- 목표 ----

@router.get(
    "/me/goal",
    response_model=GoalResponse,
    responses={401: {"model": HealthError}, 404: {"model": HealthError}},
)
def read_goal(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return health_service.get_goal(db, current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.put(
    "/me/goal",
    response_model=GoalResponse,
    responses={400: {"model": HealthError}, 401: {"model": HealthError}},
)
def update_goal(
    request: GoalUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return health_service.upsert_goal(
            db,
            current_user.id,
            goal_type=request.goal_type,
            target_kcal=request.target_kcal,
            target_weight_kg=request.target_weight_kg,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


# ---- 홈 진행률 요약 ----

@router.get(
    "/me/summary",
    response_model=SummaryResponse,
    responses={401: {"model": HealthError}},
)
def read_summary(
    target_date: date | None = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    return health_service.get_summary(db, current_user.id, resolved_date)


# ---- 주/월 추이 ----

@router.get(
    "/me/trends",
    response_model=TrendsResponse,
    responses={400: {"model": HealthError}, 401: {"model": HealthError}},
)
def read_trends(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return health_service.get_trends(db, current_user.id, start_date, end_date)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


# ---- 끼니 ----

@router.post(
    "/meals",
    response_model=MealResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": HealthError}},
)
def create_meal(
    request: MealCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return health_service.create_meal(
        db,
        current_user.id,
        meal_type=request.meal_type,
        logged_at=request.logged_at,
        photo_s3_key=request.photo_s3_key,
        items=[item.model_dump() for item in request.items],
    )


@router.get(
    "/meals",
    response_model=list[MealResponse],
    responses={401: {"model": HealthError}},
)
def list_meals(
    target_date: date | None = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    return health_service.list_meals(db, current_user.id, resolved_date)


@router.put(
    "/meals/{meal_id}",
    response_model=MealResponse,
    responses={401: {"model": HealthError}, 404: {"model": HealthError}},
)
def update_meal(
    meal_id: int,
    request: MealUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return health_service.update_meal(
            db,
            current_user.id,
            meal_id,
            meal_type=request.meal_type,
            logged_at=request.logged_at,
            photo_s3_key=request.photo_s3_key,
            items=[item.model_dump() for item in request.items],
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.delete(
    "/meals/{meal_id}",
    response_model=MessageResponse,
    responses={401: {"model": HealthError}, 404: {"model": HealthError}},
)
def delete_meal(
    meal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        health_service.soft_delete_meal(db, current_user.id, meal_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return {"message": "끼니 기록을 삭제했습니다."}


# ---- 체중 ----

@router.post(
    "/weights",
    response_model=WeightResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": HealthError}},
)
def create_weight(
    request: WeightCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return health_service.create_weight(
        db,
        current_user.id,
        weight_kg=request.weight_kg,
        measured_at=request.measured_at,
    )


@router.get(
    "/weights",
    response_model=list[WeightResponse],
    responses={401: {"model": HealthError}},
)
def list_weights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return health_service.list_weights(db, current_user.id)
