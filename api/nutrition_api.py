from fastapi import APIRouter, HTTPException, status

from api.dependencies import DB, ConsentedUser, CurrentUser
from schemas.common_schema import ErrorResponse
from schemas.nutrition_schema import (
    NutritionEstimateRequest,
    NutritionEstimateResponse,
    NutritionWarningsRequest,
    NutritionWarningsResponse,
)
from services.nutrition_service import (
    NutritionUnavailableError,
    estimate_nutrition,
    get_record_warnings_response,
)

router = APIRouter()


@router.post(
    "/nutrition/estimate",
    response_model=NutritionEstimateResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def estimate(request: NutritionEstimateRequest, _current_user: CurrentUser, db: DB):
    # 미매칭(추정도 실패)은 404(FoodNotFoundError) — 앱의 kcal 수동 입력 경로로 유도한다 (19장).
    try:
        nutrition, cached = estimate_nutrition(db, request.food_label)
    except NutritionUnavailableError as error:
        # 추정 백엔드 장애 — 미매칭이 아니다. 앱은 재시도 또는 수동 입력으로 안내한다 (19장).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    # Numeric(Decimal) 컬럼은 response_model 검증(lax)이 float 로 바꾼다. `cached` 는 ORM 에 없는
    # 필수 필드라 model_validate(nutrition) 로는 만들 수 없어 필드를 나열한다.
    return {
        "food_label": nutrition.food_label,
        "kcal_per_serving": nutrition.kcal_per_serving,
        "serving_desc": nutrition.serving_desc,
        "serving_size_g": nutrition.serving_size_g,
        "carbs_g": nutrition.carbs_g,
        "protein_g": nutrition.protein_g,
        "fat_g": nutrition.fat_g,
        # 신장병 사용자가 먹은 음식의 나트륨·칼륨·인을 확인한다 (CKD_NUTRITION.md 3-5).
        "sodium_mg": nutrition.sodium_mg,
        "potassium_mg": nutrition.potassium_mg,
        "phosphorus_mg": nutrition.phosphorus_mg,
        "source": nutrition.source,
        "created_at": nutrition.created_at,
        "cached": cached,
    }


@router.post(
    "/nutrition/warnings",
    response_model=NutritionWarningsResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def read_record_warnings(
    request: NutritionWarningsRequest,
    # 질병·알러지를 조회에 사용하므로 sensitive_health 동의 필수 (DATA_MODEL.md 16장, 7장 규약).
    current_user: ConsentedUser,
    db: DB,
):
    return get_record_warnings_response(db, current_user.id, request.food_labels)
