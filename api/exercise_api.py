from datetime import date, datetime

from timeutil import UTC

from fastapi import APIRouter, Query, status

from api.dependencies import DB, CurrentUser
from schemas.common_schema import ErrorResponse
from schemas.exercise_schema import (
    ExerciseCreateRequest,
    ExerciseGoalRequest,
    ExerciseGoalResponse,
    ExerciseListResponse,
    ExerciseResponse,
    ExerciseSummaryResponse,
    ExerciseTypeOption,
)
from services import exercise_service

router = APIRouter()


@router.get(
    "/exercise-types",
    response_model=list[ExerciseTypeOption],
    responses={401: {"model": ErrorResponse}},
)
def read_exercise_types(_current_user: CurrentUser):
    # 선택지는 fitness_rules 가 단일 진실이다 — 앱이 목록을 하드코딩하지 않게 서버가 준다.
    return exercise_service.list_exercise_types()


@router.post(
    "/exercises",
    response_model=ExerciseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def create_exercise(request: ExerciseCreateRequest, current_user: CurrentUser, db: DB):
    exercise = exercise_service.create_exercise(db, current_user.id, **request.model_dump())
    return exercise_service.to_response(exercise)


@router.get(
    "/exercises",
    response_model=ExerciseListResponse,
    responses={401: {"model": ErrorResponse}},
)
def read_exercises(
    current_user: CurrentUser,
    db: DB,
    target_date: date | None = Query(default=None, alias="date"),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    exercises = exercise_service.list_exercises(db, current_user.id, resolved_date)

    return {"exercises": [exercise_service.to_response(row) for row in exercises]}


@router.put(
    "/exercises/{exercise_id}",
    response_model=ExerciseResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def update_exercise(
    exercise_id: int,
    request: ExerciseCreateRequest,
    current_user: CurrentUser,
    db: DB,
):
    # 전체 교체 수정. 끼니 PUT 과 같은 방식이다. 남의 기록·삭제된 기록·없는 기록은 전부 404 —
    # 존재를 알려주지 않는다 (끼니와 같은 규칙).
    exercise = exercise_service.update_exercise(
        db, current_user.id, exercise_id, **request.model_dump()
    )
    return exercise_service.to_response(exercise)


@router.delete(
    "/exercises/{exercise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_exercise(exercise_id: int, current_user: CurrentUser, db: DB):
    exercise_service.delete_exercise(db, current_user.id, exercise_id)


@router.get(
    "/me/exercise-summary",
    response_model=ExerciseSummaryResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def read_exercise_summary(
    current_user: CurrentUser,
    db: DB,
    start_date: date = Query(...),
    end_date: date = Query(...),
):
    return exercise_service.get_summary(db, current_user.id, start_date, end_date)


@router.get(
    "/me/exercise-goal",
    response_model=ExerciseGoalResponse,
    responses={401: {"model": ErrorResponse}},
)
def read_exercise_goal(current_user: CurrentUser, db: DB):
    # 목표를 설정하지 않았으면 지침 권장량이 기본값으로 내려간다 (is_default=true).
    return exercise_service.resolve_goal(db, current_user.id)


@router.put(
    "/me/exercise-goal",
    response_model=ExerciseGoalResponse,
    responses={401: {"model": ErrorResponse}},
)
def update_exercise_goal(request: ExerciseGoalRequest, current_user: CurrentUser, db: DB):
    exercise_service.upsert_goal(db, current_user.id, **request.model_dump())
    return exercise_service.resolve_goal(db, current_user.id)
