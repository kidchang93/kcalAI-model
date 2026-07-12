from datetime import date, datetime

from timeutil import UTC

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.consent_api import require_sensitive_consent
from database import get_db
from models.auth_model import User
from schemas.health_schema import MealType
from schemas.recommendation_schema import RecommendationError, RecommendationResponse
from services.recommendation_service import get_recommendation

router = APIRouter()


@router.get(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={
        401: {"model": RecommendationError},
        403: {"model": RecommendationError},
    },
)
def read_recommendation(
    meal_type: MealType = Query(...),
    target_date: date | None = Query(default=None, alias="date"),
    # 질병·알러지를 조회에 사용하므로 sensitive_health 동의 필수 (DATA_MODEL.md 11장, 7장 규약).
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()

    # 추천은 식약처 DB 규칙 기반으로 항상 생성된다 — LLM·502 없음 (13장).
    recommendation, cached = get_recommendation(db, current_user.id, resolved_date, meal_type)

    return {
        "meal_type": recommendation.meal_type,
        "rec_date": recommendation.rec_date,
        "items": recommendation.items,
        "excluded": recommendation.excluded,
        "cached": cached,
    }
