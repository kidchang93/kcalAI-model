from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.pet_schema import (
    FeedingCreateRequest,
    FeedingResponse,
    MessageResponse,
    PetError,
    PetResponse,
    PetUpsertRequest,
)
from services import pet_service

router = APIRouter()


# ---- 반려동물 ----

@router.post(
    "/pets",
    response_model=PetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": PetError}},
)
def create_pet(
    request: PetUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return pet_service.create_pet(
        db,
        current_user.id,
        name=request.name,
        species=request.species,
        breed=request.breed,
        birth_year=request.birth_year,
        weight_kg=request.weight_kg,
        is_neutered=request.is_neutered,
    )


@router.get(
    "/pets",
    response_model=list[PetResponse],
    responses={401: {"model": PetError}},
)
def list_pets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return pet_service.list_pets(db, current_user.id)


@router.put(
    "/pets/{pet_id}",
    response_model=PetResponse,
    responses={401: {"model": PetError}, 404: {"model": PetError}},
)
def update_pet(
    pet_id: int,
    request: PetUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return pet_service.update_pet(
            db,
            current_user.id,
            pet_id,
            name=request.name,
            species=request.species,
            breed=request.breed,
            birth_year=request.birth_year,
            weight_kg=request.weight_kg,
            is_neutered=request.is_neutered,
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.delete(
    "/pets/{pet_id}",
    response_model=MessageResponse,
    responses={401: {"model": PetError}, 404: {"model": PetError}},
)
def delete_pet(
    pet_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        pet_service.soft_delete_pet(db, current_user.id, pet_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return {"message": "반려동물을 삭제했습니다."}


# ---- 급여 기록 ----

@router.post(
    "/pets/{pet_id}/feedings",
    response_model=FeedingResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": PetError}, 404: {"model": PetError}},
)
def create_feeding(
    pet_id: int,
    request: FeedingCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return pet_service.create_feeding(
            db,
            current_user.id,
            pet_id,
            food_label=request.food_label,
            amount_g=request.amount_g,
            kcal=request.kcal,
            fed_at=request.fed_at,
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get(
    "/pets/{pet_id}/feedings",
    response_model=list[FeedingResponse],
    responses={401: {"model": PetError}, 404: {"model": PetError}},
)
def list_feedings(
    pet_id: int,
    target_date: date | None = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()
    try:
        return pet_service.list_feedings(db, current_user.id, pet_id, resolved_date)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
