from datetime import date
from typing import Literal

from pydantic import BaseModel

from schemas.health_schema import MealType


class RecommendationItem(BaseModel):
    name: str
    # 식약처 실측 DB 의 1인분 kcal (12장). disclaimer 고지 대상이다.
    kcal: int
    reason: str
    # 1인분 실측 영양값 (식약처/농진청 DB). 미측정·원물 행은 None.
    # 신장병 등 질병 환자가 나트륨·칼륨·인·단백질을 눈으로 확인하게 노출한다
    # (docs/CKD_NUTRITION.md 3-1). 처방이 아니라 실측값 표시다.
    sodium_mg: float | None = None
    potassium_mg: float | None = None
    phosphorus_mg: float | None = None
    protein_g: float | None = None


class ExcludedCriterion(BaseModel):
    # 후보 풀 제외에 반영된 조건 명세.
    type: Literal["allergen", "condition"]
    code: str
    label: str


class ExcludedFiltered(BaseModel):
    # 후처리 안전 필터로 실제 탈락한 후보.
    type: Literal["filtered"]
    name: str
    matched_keyword: str


class RecommendationResponse(BaseModel):
    meal_type: MealType
    rec_date: date
    items: list[RecommendationItem]
    excluded: list[ExcludedCriterion | ExcludedFiltered]
    # 사용자 질병 기반 식이 안내 문구. 신장병이면 칼륨 저감 조리법 등 (docs/CKD_NUTRITION.md 3-1).
    # 비해당 사용자는 빈 배열. 지침 근거의 상대 안내이며 처방이 아니다.
    tips: list[str] = []
    # 캐시에서 나왔는지 여부. false 면 이번 요청에서 새로 생성한 것이다 (규칙 기반, 13장).
    cached: bool
    # 서버가 내려보낸다 — 앱 하드코딩 문구가 화면마다 어긋나는 것을 막는다.
    # 전문가 감수 전까지 문구를 바꾸지 않는다 (DATA_MODEL.md 11장).
    disclaimer: str = "AI 추정값이며 의학적 조언이 아닙니다."


class RecommendationError(BaseModel):
    detail: str
