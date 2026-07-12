from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.group_schema import (
    GroupCreateRequest,
    GroupDetailResponse,
    GroupError,
    GroupJoinRequest,
    GroupPetAttachRequest,
    GroupSummary,
    MessageResponse,
)
from services import group_service

router = APIRouter()


@router.post(
    "/groups",
    response_model=GroupSummary,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": GroupError}},
)
def create_group(
    request: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return group_service.create_group(db, current_user.id, name=request.name, kind=request.kind)


@router.get(
    "/groups",
    response_model=list[GroupSummary],
    responses={401: {"model": GroupError}},
)
def list_groups(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return group_service.list_my_groups(db, current_user.id)


@router.post(
    "/groups/join",
    response_model=GroupSummary,
    responses={400: {"model": GroupError}, 401: {"model": GroupError}, 404: {"model": GroupError}},
)
def join_group(
    request: GroupJoinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return group_service.join_group(db, current_user.id, request.invite_code)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get(
    "/groups/{group_id}",
    response_model=GroupDetailResponse,
    responses={401: {"model": GroupError}, 403: {"model": GroupError}, 404: {"model": GroupError}},
)
def read_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return group_service.get_group_detail(db, current_user.id, group_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.post(
    "/groups/{group_id}/pets",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": GroupError},
        401: {"model": GroupError},
        403: {"model": GroupError},
        404: {"model": GroupError},
    },
)
def attach_pet(
    group_id: int,
    request: GroupPetAttachRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        group_service.attach_pet(db, current_user.id, group_id, request.pet_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return {"message": "반려동물을 그룹에 참여시켰습니다."}


# "me" 가 아래 /members/{user_id} 의 int 매개변수에 걸리지 않도록 먼저 등록한다.
@router.delete(
    "/groups/{group_id}/members/me",
    response_model=MessageResponse,
    responses={400: {"model": GroupError}, 401: {"model": GroupError}, 404: {"model": GroupError}},
)
def leave_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        group_service.leave_group(db, current_user.id, group_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return {"message": "그룹에서 탈퇴했습니다."}


@router.delete(
    "/groups/{group_id}/members/{user_id}",
    response_model=MessageResponse,
    responses={
        400: {"model": GroupError},
        401: {"model": GroupError},
        403: {"model": GroupError},
        404: {"model": GroupError},
    },
)
def remove_member(
    group_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        group_service.remove_member(db, current_user.id, group_id, user_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return {"message": "멤버를 그룹에서 제거했습니다."}


@router.delete(
    "/groups/{group_id}",
    response_model=MessageResponse,
    responses={401: {"model": GroupError}, 403: {"model": GroupError}, 404: {"model": GroupError}},
)
def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        group_service.delete_group(db, current_user.id, group_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    return {"message": "그룹을 삭제했습니다."}


@router.delete(
    "/groups/{group_id}/pets/{pet_id}",
    response_model=MessageResponse,
    responses={401: {"model": GroupError}, 403: {"model": GroupError}, 404: {"model": GroupError}},
)
def detach_pet(
    group_id: int,
    pet_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        group_service.detach_pet(db, current_user.id, group_id, pet_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    return {"message": "반려동물의 그룹 참여를 해제했습니다."}
