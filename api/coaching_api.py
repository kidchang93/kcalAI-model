from datetime import datetime

from timeutil import UTC

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.consent_api import require_sensitive_consent
from database import get_db
from models.auth_model import User
from schemas.coaching_schema import CoachingError, CoachingResponse
from services import coaching_service

router = APIRouter()


@router.get(
    "/me/coaching",
    response_model=CoachingResponse,
    responses={401: {"model": CoachingError}, 403: {"model": CoachingError}},
)
def read_weekly_coaching(
    # 조언이 질병을 반영하므로(강도 제시를 피하고 상담을 안내) sensitive_health 동의가 필수다.
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    return coaching_service.get_weekly_coaching(db, current_user.id, datetime.now(UTC).date())
