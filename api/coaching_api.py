from datetime import datetime

from timeutil import UTC

from fastapi import APIRouter

from api.dependencies import DB, ConsentedUser
from schemas.coaching_schema import CoachingResponse
from schemas.common_schema import ErrorResponse
from services import coaching_service

router = APIRouter()


@router.get(
    "/me/coaching",
    response_model=CoachingResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def read_weekly_coaching(
    # 조언이 질병을 반영하므로(강도 제시를 피하고 상담을 안내) sensitive_health 동의가 필수다.
    current_user: ConsentedUser,
    db: DB,
):
    return coaching_service.get_weekly_coaching(db, current_user.id, datetime.now(UTC).date())
