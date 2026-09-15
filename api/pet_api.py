from datetime import date, datetime

from timeutil import UTC

from fastapi import APIRouter, Query, status

from api.dependencies import DB, CurrentUser
from schemas.common_schema import ErrorResponse, MessageResponse
from schemas.pet_schema import FeedingCreateRequest, FeedingResponse, PetResponse, PetUpsertRequest
from services import pet_service

router = APIRouter()


# ---- 반려동물 ----

@router.post(
    "/pets",
    response_model=PetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}},
)
def create_pet(request: PetUpsertRequest, current_user: CurrentUser, db: DB):
    return pet_service.create_pet(db, current_user.id, **request.model_dump())


@router.get(
    "/pets",
    response_model=list[PetResponse],
    responses={401: {"model": ErrorResponse}},
)
def list_pets(current_user: CurrentUser, db: DB):
    return pet_service.list_pets(db, current_user.id)


@router.put(
    "/pets/{pet_id}",
    response_model=PetResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_pet(pet_id: int, request: PetUpsertRequest, current_user: CurrentUser, db: DB):
    return pet_service.update_pet(db, current_user.id, pet_id, **request.model_dump())


@router.delete(
    "/pets/{pet_id}",
    response_model=MessageResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_pet(pet_id: int, current_user: CurrentUser, db: DB):
    pet_service.soft_delete_pet(db, current_user.id, pet_id)
    return {"message": "반려동물을 삭제했습니다."}


# ---- 급여 기록 ----

@router.post(
    "/pets/{pet_id}/feedings",
    response_model=FeedingResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def create_feeding(pet_id: int, request: FeedingCreateRequest, current_user: CurrentUser, db: DB):
    return pet_service.create_feeding(db, current_user.id, pet_id, **request.model_dump())


@router.get(
    "/pets/{pet_id}/feedings",
    response_model=list[FeedingResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_feedings(
    pet_id: int,
    current_user: CurrentUser,
    db: DB,
    target_date: date | None = Query(default=None, alias="date"),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    return pet_service.list_feedings(db, current_user.id, pet_id, resolved_date)
