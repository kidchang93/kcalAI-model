from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.meta_schema import MetaError, MetaOptionsResponse
from services import meta_service

router = APIRouter()


@router.get(
    "/meta/options",
    response_model=MetaOptionsResponse,
    responses={401: {"model": MetaError}},
)
def read_options(
    # Bearer 필수(7장 규약 일관). 동의 화면 다음이 질병 선택이므로
    # sensitive_health 동의는 요구하지 않는다 (DATA_MODEL.md 10장).
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
    }
