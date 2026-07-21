from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.challenge_schema import (
    ChallengeCreateRequest,
    ChallengeDetailResponse,
    ChallengeError,
    ChallengeListResponse,
    ChallengeSummary,
)
from services import challenge_service

router = APIRouter()


@router.post(
    "/groups/{group_id}/challenges",
    response_model=ChallengeSummary,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ChallengeError},
        401: {"model": ChallengeError},
        404: {"model": ChallengeError},
    },
)
def create_challenge(
    group_id: int,
    request: ChallengeCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        challenge = challenge_service.create_challenge(
            db,
            current_user.id,
            group_id,
            title=request.title,
            target_minutes=request.target_minutes,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except LookupError as error:
        # 비멤버에게는 그룹의 존재를 알려주지 않는다 (그룹 라우트와 같은 은닉 규칙).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return challenge_service.to_summary(challenge)


@router.get(
    "/groups/{group_id}/challenges",
    response_model=ChallengeListResponse,
    responses={401: {"model": ChallengeError}, 404: {"model": ChallengeError}},
)
def read_challenges(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        challenges = challenge_service.list_challenges(db, current_user.id, group_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return {"challenges": [challenge_service.to_summary(row) for row in challenges]}


@router.get(
    "/groups/{group_id}/challenges/{challenge_id}",
    response_model=ChallengeDetailResponse,
    responses={401: {"model": ChallengeError}, 404: {"model": ChallengeError}},
)
def read_challenge_detail(
    group_id: int,
    challenge_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return challenge_service.get_challenge_detail(
            db, current_user.id, group_id, challenge_id
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.delete(
    "/groups/{group_id}/challenges/{challenge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ChallengeError},
        403: {"model": ChallengeError},
        404: {"model": ChallengeError},
    },
)
def delete_challenge(
    group_id: int,
    challenge_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        challenge_service.delete_challenge(db, current_user.id, group_id, challenge_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        # 만든 사람도 그룹 소유자도 아니면 403 — 존재 자체는 이미 멤버에게 공개돼 있다.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
