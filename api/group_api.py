from fastapi import APIRouter, status

from api.dependencies import DB, CurrentUser
from schemas.common_schema import ErrorResponse, MessageResponse
from schemas.group_schema import (
    GroupCreateRequest,
    GroupDetailResponse,
    GroupJoinRequest,
    GroupPetAttachRequest,
    GroupSummary,
)
from services import group_service

router = APIRouter()


@router.post(
    "/groups",
    response_model=GroupSummary,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}},
)
def create_group(request: GroupCreateRequest, current_user: CurrentUser, db: DB):
    return group_service.create_group(db, current_user.id, name=request.name, kind=request.kind)


@router.get(
    "/groups",
    response_model=list[GroupSummary],
    responses={401: {"model": ErrorResponse}},
)
def list_groups(current_user: CurrentUser, db: DB):
    return group_service.list_my_groups(db, current_user.id)


@router.post(
    "/groups/join",
    response_model=GroupSummary,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def join_group(request: GroupJoinRequest, current_user: CurrentUser, db: DB):
    return group_service.join_group(db, current_user.id, request.invite_code)


@router.get(
    "/groups/{group_id}",
    response_model=GroupDetailResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_group(group_id: int, current_user: CurrentUser, db: DB):
    return group_service.get_group_detail(db, current_user.id, group_id)


@router.post(
    "/groups/{group_id}/pets",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def attach_pet(group_id: int, request: GroupPetAttachRequest, current_user: CurrentUser, db: DB):
    group_service.attach_pet(db, current_user.id, group_id, request.pet_id)
    return {"message": "반려동물을 그룹에 참여시켰습니다."}


# "me" 가 아래 /members/{user_id} 의 int 매개변수에 걸리지 않도록 먼저 등록한다.
@router.delete(
    "/groups/{group_id}/members/me",
    response_model=MessageResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def leave_group(group_id: int, current_user: CurrentUser, db: DB):
    group_service.leave_group(db, current_user.id, group_id)
    return {"message": "그룹에서 탈퇴했습니다."}


@router.delete(
    "/groups/{group_id}/members/{user_id}",
    response_model=MessageResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def remove_member(group_id: int, user_id: int, current_user: CurrentUser, db: DB):
    group_service.remove_member(db, current_user.id, group_id, user_id)
    return {"message": "멤버를 그룹에서 제거했습니다."}


@router.delete(
    "/groups/{group_id}",
    response_model=MessageResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_group(group_id: int, current_user: CurrentUser, db: DB):
    group_service.delete_group(db, current_user.id, group_id)
    return {"message": "그룹을 삭제했습니다."}


@router.delete(
    "/groups/{group_id}/pets/{pet_id}",
    response_model=MessageResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def detach_pet(group_id: int, pet_id: int, current_user: CurrentUser, db: DB):
    group_service.detach_pet(db, current_user.id, group_id, pet_id)
    return {"message": "반려동물의 그룹 참여를 해제했습니다."}
