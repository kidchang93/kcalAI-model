import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from log_utils import setup_level_logger
from models.auth_model import User
from schemas.nutrition_schema import (
    NutritionError,
    NutritionEstimateRequest,
    NutritionEstimateResponse,
)
from services.nutrition_service import NutritionEstimateError, estimate_nutrition

error_logger = setup_level_logger(logging.ERROR)

router = APIRouter()


@router.post(
    "/nutrition/estimate",
    response_model=NutritionEstimateResponse,
    responses={401: {"model": NutritionError}, 502: {"model": NutritionError}},
)
def estimate(
    request: NutritionEstimateRequest,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        nutrition, cached = estimate_nutrition(db, request.food_label)
    except NutritionEstimateError as error:
        error_logger.error(f"nutrition estimate 실패 label={request.food_label!r}: {error!r}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
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
