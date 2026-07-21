from datetime import date, datetime

from timeutil import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.exercise_schema import (
    ExerciseCreateRequest,
    ExerciseError,
    ExerciseListResponse,
    ExerciseResponse,
    ExerciseSummaryResponse,
    ExerciseTypeOption,
    ExerciseUpdateRequest,
)
from services import exercise_service

router = APIRouter()


@router.get(
    "/exercise-types",
    response_model=list[ExerciseTypeOption],
    responses={401: {"model": ExerciseError}},
)
def read_exercise_types(_current_user: User = Depends(get_current_user)):
    # 선택지는 fitness_rules 가 단일 진실이다 — 앱이 목록을 하드코딩하지 않게 서버가 준다.
    return exercise_service.list_exercise_types()


@router.post(
    "/exercises",
    response_model=ExerciseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ExerciseError}, 401: {"model": ExerciseError}},
)
def create_exercise(
    request: ExerciseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        exercise = exercise_service.create_exercise(
            db,
            current_user.id,
            exercise_type=request.exercise_type,
            duration_minutes=request.duration_minutes,
            intensity=request.intensity,
            kcal=request.kcal,
            performed_at=request.performed_at,
            memo=request.memo,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    return exercise_service.to_response(exercise)


@router.get(
    "/exercises",
    response_model=ExerciseListResponse,
    responses={401: {"model": ExerciseError}},
)
def read_exercises(
    target_date: date | None = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    exercises = exercise_service.list_exercises(db, current_user.id, resolved_date)

    return {"exercises": [exercise_service.to_response(row) for row in exercises]}


@router.put(
    "/exercises/{exercise_id}",
    response_model=ExerciseResponse,
    responses={
        400: {"model": ExerciseError},
        401: {"model": ExerciseError},
        404: {"model": ExerciseError},
    },
)
def update_exercise(
    exercise_id: int,
    request: ExerciseUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        exercise = exercise_service.update_exercise(
            db,
            current_user.id,
            exercise_id,
            exercise_type=request.exercise_type,
            duration_minutes=request.duration_minutes,
            intensity=request.intensity,
            kcal=request.kcal,
            performed_at=request.performed_at,
            memo=request.memo,
        )
    except LookupError as error:
        # 남의 기록·삭제된 기록·없는 기록 전부 404 — 존재를 알려주지 않는다 (끼니와 같은 규칙).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    return exercise_service.to_response(exercise)


@router.delete(
    "/exercises/{exercise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ExerciseError}, 404: {"model": ExerciseError}},
)
def delete_exercise(
    exercise_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        exercise_service.delete_exercise(db, current_user.id, exercise_id)
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error


@router.get(
    "/me/exercise-summary",
    response_model=ExerciseSummaryResponse,
    responses={400: {"model": ExerciseError}, 401: {"model": ExerciseError}},
)
def read_exercise_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return exercise_service.get_summary(db, current_user.id, start_date, end_date)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
