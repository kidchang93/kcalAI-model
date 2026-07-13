"""Gemini 기반 영양 추정 — 데이터셋에 없는 라벨을 **1회만** 추정한다 (DATA_MODEL.md 19장).

조회 경로에 LLM은 없다. estimate의 데이터셋 4단계와 llm 캐시가 **모두** 실패했을 때만
이 모듈이 호출되고, 결과는 food_nutrition(source='llm')에 insert 되어 **동결**된다.
같은 라벨의 다음 요청은 그 행을 그대로 읽으므로 LLM의 값 흔들림이 사용자에게 보이지 않는다
(13장의 결정성 원칙 유지).

추정값을 무검증으로 적재하면 DB가 영구히 오염되므로, 적재 전에 게이트를 통과시킨다.
탈락한 추정은 **버리고** 404로 떨어뜨린다 — 엉터리 값을 남기느니 수동 입력이 정직하다.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from log_utils import setup_level_logger
from services.gemini_client import GEMINI_MODEL, GeminiError, generate_json

info_logger = setup_level_logger(logging.INFO)
error_logger = setup_level_logger(logging.ERROR)

# 적재 게이트 — 1인분 kcal 허용 범위. 밖이면 추정 실패로 본다(음료 1kcal ~ 고열량 정식 2000kcal).
_MIN_KCAL = 1
_MAX_KCAL = 2000
# 매크로 정합성: carbs*4 + protein*4 + fat*9 가 kcal과 이 비율 이상 어긋나면 폐기한다.
_MACRO_TOLERANCE = 0.30
# 매크로 검증 하한 — 저열량 음식은 반올림 오차가 커서 비율 검증이 무의미하다.
_MACRO_CHECK_MIN_KCAL = 50

# temperature=0 — 같은 라벨의 응답 변동을 줄인다. 어차피 1회만 부르지만, 그 1회가 흔들릴수록
# 동결되는 값의 품질이 나빠진다.
_TEMPERATURE = 0.0

_PROMPT_TEMPLATE = (
    "다음 음식의 **1인분 기준** 영양 정보를 추정하세요: '{food_label}'\n\n"
    "규칙:\n"
    "- kcal_per_serving: 1인분 열량(정수 kcal).\n"
    "- serving_desc: 1인분의 기준을 한국어로 짧게 (예: '1인분(약 350g)', '1잔(200ml)').\n"
    "- carbs_g / protein_g / fat_g: 1인분의 탄수화물·단백질·지방(g). 소수 1자리까지.\n"
    "- 매크로 합이 열량과 맞아야 합니다 (탄수화물·단백질 4kcal/g, 지방 9kcal/g).\n"
    "- 한국인의 일반적인 1인분 기준으로 추정하세요.\n"
    "- 음식이 아니거나(사물·사람 등) 무엇인지 알 수 없으면 is_food를 false로 두세요."
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_food": {"type": "boolean"},
        "kcal_per_serving": {"type": "integer"},
        "serving_desc": {"type": "string"},
        "carbs_g": {"type": "number", "nullable": True},
        "protein_g": {"type": "number", "nullable": True},
        "fat_g": {"type": "number", "nullable": True},
    },
    "required": ["is_food", "kcal_per_serving", "serving_desc"],
}


class NutritionEstimationError(Exception):
    """추정 불가 — 음식이 아니거나 게이트 탈락. 라우트가 404(수동 입력 유도)로 처리한다."""


class NutritionEstimationUnavailable(Exception):
    """Gemini 호출 자체가 실패(장애·타임아웃·키 없음). 라우트가 503으로 처리한다.

    '이 음식은 DB에 없다'(404)와 '지금 서버가 추정을 못 한다'(503)는 다른 사건이다.
    후자를 404로 감추면 장애가 미매칭 통계에 묻힌다.
    """


@dataclass(frozen=True)
class EstimatedNutrition:
    kcal_per_serving: int
    serving_desc: str
    carbs_g: Decimal | None
    protein_g: Decimal | None
    fat_g: Decimal | None


def _to_decimal(value: object) -> Decimal | None:
    """소수 1자리 Decimal로. 음수·비수치는 None으로 떨어뜨린다 (컬럼이 Numeric(6,1))."""
    if value is None:
        return None
    try:
        number = Decimal(str(value)).quantize(Decimal("0.1"))
    except (ArithmeticError, ValueError):
        return None
    if number < 0 or number > Decimal("9999.9"):
        return None
    return number


def _macros_consistent(
    kcal: int, carbs: Decimal | None, protein: Decimal | None, fat: Decimal | None
) -> bool:
    """매크로 합이 열량과 정합한가. 하나라도 없으면 검증을 건너뛴다(값은 그대로 적재)."""
    if carbs is None or protein is None or fat is None:
        return True
    if kcal < _MACRO_CHECK_MIN_KCAL:
        return True

    derived = float(carbs) * 4 + float(protein) * 4 + float(fat) * 9
    return abs(derived - kcal) / kcal <= _MACRO_TOLERANCE


def estimate_by_label(food_label: str) -> EstimatedNutrition:
    """라벨 하나를 Gemini로 추정해 검증된 영양값을 돌려준다. 호출자가 DB에 적재한다.

    - 음식이 아니거나 게이트 탈락 → NutritionEstimationError (404)
    - Gemini 장애·키 없음 → NutritionEstimationUnavailable (503)
    """
    try:
        data, duration_ms = generate_json(
            contents=[_PROMPT_TEMPLATE.format(food_label=food_label)],
            response_schema=_RESPONSE_SCHEMA,
            temperature=_TEMPERATURE,
        )
    except GeminiError as error:
        raise NutritionEstimationUnavailable(str(error)) from error

    if not data.get("is_food"):
        raise NutritionEstimationError(f"음식으로 판단되지 않음: {food_label}")

    try:
        kcal = int(data["kcal_per_serving"])
    except (KeyError, TypeError, ValueError) as error:
        raise NutritionEstimationError(f"kcal 파싱 실패: {food_label}") from error

    if not _MIN_KCAL <= kcal <= _MAX_KCAL:
        raise NutritionEstimationError(f"kcal 범위 이탈({kcal}): {food_label}")

    carbs = _to_decimal(data.get("carbs_g"))
    protein = _to_decimal(data.get("protein_g"))
    fat = _to_decimal(data.get("fat_g"))

    if not _macros_consistent(kcal, carbs, protein, fat):
        # 매크로만 버리고 kcal은 살린다 — 사용자에게 kcal이 핵심이고, macros는 nullable이다.
        error_logger.error(
            f"nutrition estimate 매크로 불일치 → macros 폐기 label={food_label} kcal={kcal}"
        )
        carbs = protein = fat = None

    serving_desc = str(data.get("serving_desc") or "1인분").strip()[:100]

    info_logger.info(
        f"nutrition estimate ok model={GEMINI_MODEL} duration_ms={duration_ms:.1f} "
        f"label={food_label} kcal={kcal}"
    )
    return EstimatedNutrition(
        kcal_per_serving=kcal,
        serving_desc=serving_desc,
        carbs_g=carbs,
        protein_g=protein,
        fat_g=fat,
    )
