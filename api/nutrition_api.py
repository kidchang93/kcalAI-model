from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.consent_api import require_sensitive_consent
from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.nutrition_schema import (
    NutritionError,
    NutritionEstimateRequest,
    NutritionEstimateResponse,
    NutritionWarningsRequest,
    NutritionWarningsResponse,
)
from services.nutrition_service import FoodNotFoundError, estimate_nutrition, get_record_warnings

router = APIRouter()


@router.post(
    "/nutrition/estimate",
    response_model=NutritionEstimateResponse,
    responses={401: {"model": NutritionError}, 404: {"model": NutritionError}},
)
def estimate(
    request: NutritionEstimateRequest,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        nutrition, cached = estimate_nutrition(db, request.food_label)
    except FoodNotFoundError as error:
        # 미매칭은 오류가 아니라 앱의 kcal 수동 입력 경로로 유도한다 (DATA_MODEL.md 13장).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return {
        "food_label": nutrition.food_label,
        "kcal_per_serving": nutrition.kcal_per_serving,
        "serving_desc": nutrition.serving_desc,
        "carbs_g": float(nutrition.carbs_g) if nutrition.carbs_g is not None else None,
        "protein_g": float(nutrition.protein_g) if nutrition.protein_g is not None else None,
        "fat_g": float(nutrition.fat_g) if nutrition.fat_g is not None else None,
        "source": nutrition.source,
        "created_at": nutrition.created_at,
        "cached": cached,
    }


@router.post(
    "/nutrition/warnings",
    response_model=NutritionWarningsResponse,
    responses={401: {"model": NutritionError}, 403: {"model": NutritionError}},
)
def read_record_warnings(
    request: NutritionWarningsRequest,
    # 질병·알러지를 조회에 사용하므로 sensitive_health 동의 필수 (DATA_MODEL.md 16장, 7장 규약).
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    return {"warnings": get_record_warnings(db, current_user.id, request.food_labels)}
