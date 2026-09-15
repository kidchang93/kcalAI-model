from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class NutritionEstimateRequest(BaseModel):
    food_label: str = Field(..., min_length=1, max_length=100)


class NutritionEstimateResponse(BaseModel):
    # 매칭된 DB 행의 이름 — 유사도 매칭이면 요청 라벨과 다를 수 있다 (13장).
    food_label: str
    kcal_per_serving: int
    serving_desc: str
    # 1인분(serving_desc가 가리키는 1회 제공량)이 몇 g인가. 앱은 사용자 입력 g ÷ serving_size_g 로
    # kcal 을 재환산한다. ml 은 밀도≈1 로 g 취급. 값이 없으면(원물 등) NULL → 앱이 인분 모드로 폴백 (12·19장).
    serving_size_g: float | None = None
    carbs_g: float | None
    protein_g: float | None
    fat_g: float | None
    # 1인분 실측 나트륨·칼륨·인 (식약처/농진청 DB). 미측정·llm 추정 행은 None.
    # 신장병 환자가 **자기가 먹은 음식**의 수치를 확인하는 데 쓴다 (docs/CKD_NUTRITION.md 3-5).
    # 사실 데이터라 질병 정보를 읽지 않는다 — 이 라우트의 동의 요건은 그대로다(Bearer만).
    sodium_mg: float | None = None
    potassium_mg: float | None = None
    phosphorus_mg: float | None = None
    # mfds/curated/mfds_processed/mfds_raw = 실측·감수, llm = LLM 1회 추정 후 동결 (19장).
    # 앱은 llm 이면 '추정값' 배지를 노출하고 수정을 쉽게 열어 준다.
    source: str
    created_at: datetime
    # 기존 행을 읽었으면 true, 이번 요청에서 새로 추정·적재했으면 false (19장).
    cached: bool

    model_config = {"from_attributes": True}


class NutritionWarningsRequest(BaseModel):
    # 1~10개, 중복 허용 — 서버가 dedupe 한다. 라벨은 각 1~100자 (DATA_MODEL.md 16장).
    food_labels: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        ..., min_length=1, max_length=10
    )


class NutritionWarningItem(BaseModel):
    source: Literal["condition", "allergy"]
    # condition_types.code 또는 allergen_types.code
    code: str
    label: str
    # 걸린 키워드 원문 1개만 노출한다 — 전체 사전은 비노출 (16장).
    # 실측 수치만으로 발동한 경고는 걸린 키워드가 없어 **빈 문자열**이다 (3-5).
    matched_keyword: str
    matched_label: str
    # 영양소 축 경고면 sodium|potassium|phosphorus|sugar, 키워드 경고면 None.
    # 신장병·고혈압 등 영양 제한 질병은 "칼륨이 높은 편" 식으로 어느 영양소인지 알려준다
    # (docs/CKD_NUTRITION.md 3-3). 처방이 아니라 지침 상대 분류다.
    nutrient: str | None = None
    # 그 축의 1인분 실측값과 상대 등급 (docs/CKD_NUTRITION.md 3-5). 앱이 "칼륨 690mg(높음)"
    # 처럼 근거를 함께 보여준다 — 수치 없이 '높은 편'만 말하면 사용자가 판단할 근거가 없다.
    # 실측이 없는 음식(간식 등 미측정)은 None 이고, 그때 경고는 이름 기반이다.
    nutrient_mg: float | None = None
    # `nutrient_mg`의 단위. **당류만 g** 이고 나머지 축은 mg 다 (2026-07-25 추가, 하위호환 —
    # 옛 앱은 이 필드를 무시하고 mg 로 표기한다). 필드명을 nutrient_mg 로 둔 채 단위를 따로
    # 내리는 이유는 계약을 깨지 않기 위해서다.
    nutrient_unit: Literal["mg", "g"] | None = None
    # 당류(sugar) 축에는 **등급이 없다** — 간식·음료 행의 1인분이 제품 한 통·한 판이라
    # 경계를 대면 거의 전부 '높음'이 된다 (`services/chronic_food_rules.py`의 실측 주석).
    tier: Literal["low", "mid", "high"] | None = None


class NutritionWarningsResponse(BaseModel):
    warnings: list[NutritionWarningItem]
    # **판정하지 못한 음식 이름** (2026-07-25 추가, 하위호환 — 옛 앱은 무시한다).
    # 경고가 없는 것과 안전한 것은 다르다. 실측이 없고 지침 키워드에도 없으면 경고가 한 건도
    # 나가지 않는데, 화면에서는 그것이 "괜찮다"로 읽힌다 — 신장병 환자의 돈까스·보쌈·통닭이
    # 그렇다. 근거가 없다는 사실 자체를 사용자에게 돌려준다 (`PRODUCT_STRATEGY.md` §0-1).
    unmeasured: list[str] = []
    # 등급(tier)을 노출할 때 함께 내리는 고지문. 해당 경고가 없으면 None (앱은 문구를 숨긴다).
    # **1인분 경계는 지침 컷오프가 아니라 1일 상한을 끼니로 나눈 정책값**이라, 그 사실을 숨기지
    # 않는 것이 노출 원칙이다 (docs/CHRONIC_NUTRITION_SOURCES.md §4-2·§6).
    notice: str | None = None
