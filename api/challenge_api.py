from fastapi import APIRouter, status

from api.dependencies import DB, CurrentUser
from schemas.challenge_schema import (
    ChallengeCreateRequest,
    ChallengeDetailResponse,
    ChallengeListResponse,
    ChallengeSummary,
)
from schemas.common_schema import ErrorResponse
from services import challenge_service

router = APIRouter()


@router.post(
    "/groups/{group_id}/challenges",
    response_model=ChallengeSummary,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def create_challenge(
    group_id: int,
    request: ChallengeCreateRequest,
    current_user: CurrentUser,
    db: DB,
):
    # 비멤버에게는 그룹의 존재를 알려주지 않는다(404) — 그룹 라우트와 같은 은닉 규칙.
    challenge = challenge_service.create_challenge(
        db, current_user.id, group_id, **request.model_dump()
    )
    return challenge_service.to_summary(challenge)


@router.get(
    "/groups/{group_id}/challenges",
    response_model=ChallengeListResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_challenges(group_id: int, current_user: CurrentUser, db: DB):
    challenges = challenge_service.list_challenges(db, current_user.id, group_id)
    return {"challenges": [challenge_service.to_summary(row) for row in challenges]}


@router.get(
    "/groups/{group_id}/challenges/{challenge_id}",
    response_model=ChallengeDetailResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_challenge_detail(group_id: int, challenge_id: int, current_user: CurrentUser, db: DB):
    return challenge_service.get_challenge_detail(db, current_user.id, group_id, challenge_id)


@router.delete(
    "/groups/{group_id}/challenges/{challenge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def delete_challenge(group_id: int, challenge_id: int, current_user: CurrentUser, db: DB):
    # 만든 사람도 그룹 소유자도 아니면 403 — 존재 자체는 이미 멤버에게 공개돼 있다.
    challenge_service.delete_challenge(db, current_user.id, group_id, challenge_id)
