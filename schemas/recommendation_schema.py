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
    # 수치의 상대 위치(저/중/고). 칼륨·인 제한 대상 사용자에게만 채워지고, 그 외에는 None 이다
    # — 비CKD 사용자에게 칼륨 등급은 의미 없는 노이즈다 (docs/CKD_NUTRITION.md 3-4).
    # 지침 이름 분류와 실측 mg 등급 중 엄격한 쪽이다. 목표량이 아니라 상대 안내다.
    potassium_tier: Literal["low", "mid", "high"] | None = None
    phosphorus_tier: Literal["low", "mid", "high"] | None = None


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
    # 등급(저/중/고)을 노출할 때만 채워지는 고지. 등급이 절대 기준이 아니라는 안내다
    # (docs/CKD_NUTRITION.md 3-4). 등급이 없는 사용자에겐 None.
    tier_notice: str | None = None
    # 캐시에서 나왔는지 여부. false 면 이번 요청에서 새로 생성한 것이다 (규칙 기반, 13장).
    cached: bool
    # 서버가 내려보낸다 — 앱 하드코딩 문구가 화면마다 어긋나는 것을 막는다.
    # 전문가 감수 전까지 문구를 바꾸지 않는다 (DATA_MODEL.md 11장).
    disclaimer: str = "AI 추정값이며 의학적 조언이 아닙니다."


class RecommendationError(BaseModel):
    detail: str
