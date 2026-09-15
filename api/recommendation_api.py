from datetime import date, datetime

from timeutil import UTC

from fastapi import APIRouter, Query

from api.dependencies import DB, ConsentedUser
from schemas.common_schema import ErrorResponse
from schemas.health_schema import MealType
from schemas.recommendation_schema import RecommendationResponse
from services.recommendation_service import get_recommendation

router = APIRouter()


@router.get(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
def read_recommendation(
    # 질병·알러지를 조회에 사용하므로 sensitive_health 동의 필수 (DATA_MODEL.md 11장, 7장 규약).
    current_user: ConsentedUser,
    db: DB,
    meal_type: MealType = Query(...),
    target_date: date | None = Query(default=None, alias="date"),
):
    resolved_date = target_date if target_date is not None else datetime.now(UTC).date()

    # 추천은 식약처 DB 규칙 기반으로 항상 생성된다 — LLM·502 없음 (13장).
    return get_recommendation(db, current_user.id, resolved_date, meal_type)
