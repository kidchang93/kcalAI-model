from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from api.dependencies import DB, CurrentUser
from schemas.common_schema import ErrorResponse
from schemas.meta_schema import MetaOptionsResponse
from services import ckd_food_rules, meta_service

router = APIRouter()


@router.get("/health")
def health_check(db: DB):
    # 외부 가동 확인(Route 53 → CloudWatch 경보)이 부른다. 인증 없이 DB까지 닿는지만 본다.
    try:
        meta_service.ping(db)
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB에 연결할 수 없어요"
        ) from error
    return {"status": "ok"}


@router.get(
    "/meta/options",
    response_model=MetaOptionsResponse,
    responses={401: {"model": ErrorResponse}},
)
def read_options(
    # Bearer 필수(7장 규약 일관). 동의 화면 다음이 질병 선택이므로
    # sensitive_health 동의는 요구하지 않는다 (DATA_MODEL.md 10장).
    _current_user: CurrentUser,
    db: DB,
):
    # dietary_tags · exclude_keywords 는 추천 엔진 내부용이라 노출하지 않는다.
    return {
        "conditions": [
            {"code": row.code, "label": row.label_ko}
            for row in meta_service.list_condition_options(db)
        ],
        "allergens": [
            {"code": row.code, "label": row.label_ko}
            for row in meta_service.list_allergen_options(db)
        ],
        # 표시 순서는 지침서 순서(투석 전 → 혈액투석 → 복막투석)를 따른다.
        "ckd_stages": [
            {"code": code, "label": label}
            for code, label in ckd_food_rules.CKD_STAGE_LABELS.items()
        ],
    }
