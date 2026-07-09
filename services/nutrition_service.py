import json
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.health_model import FoodNutrition
from schemas.gpt_schemas import GptAnswer
from services.gpt_oss_service import answerByGptOss20B


class NutritionEstimateError(RuntimeError):
    """LLM 응답을 구조화 값으로 파싱하지 못했을 때 던진다. api 가 502 로 변환한다."""


_PROMPT_TEMPLATE = (
    "너는 영양 정보 데이터베이스다. 음식 '{food_label}' 1인분의 영양 정보를 추정해라.\n"
    "반드시 아래 키를 가진 JSON 객체 하나만 출력해라. 코드블록, 설명, 단위 문자열을 붙이지 마라.\n"
    "{{\n"
    '  "kcal_per_serving": <정수 kcal>,\n'
    '  "serving_desc": "<1인분 분량 설명, 예: 1인분 (약 210g)>",\n'
    '  "carbs_g": <탄수화물 g, 숫자>,\n'
    '  "protein_g": <단백질 g, 숫자>,\n'
    '  "fat_g": <지방 g, 숫자>\n'
    "}}"
)


def estimate_nutrition(db: Session, food_label: str) -> tuple[FoodNutrition, bool]:
    label = food_label.strip()

    cached = db.scalar(select(FoodNutrition).where(FoodNutrition.food_label == label))
    if cached is not None:
        return cached, True

    parsed = _call_llm(label)
    nutrition = FoodNutrition(
        food_label=label,
        kcal_per_serving=parsed["kcal_per_serving"],
        serving_desc=parsed["serving_desc"],
        carbs_g=parsed["carbs_g"],
        protein_g=parsed["protein_g"],
        fat_g=parsed["fat_g"],
        source="llm",
    )
    db.add(nutrition)
    db.commit()
    db.refresh(nutrition)
    return nutrition, False


def _call_llm(label: str) -> dict:
    prompt = _PROMPT_TEMPLATE.format(food_label=label)

    try:
        answer = answerByGptOss20B(GptAnswer(text=prompt, max_tokens=512))
    except Exception as error:  # gpt_oss_service 는 RuntimeError 를 던진다.
        raise NutritionEstimateError("영양 정보 추정에 실패했습니다. 잠시 후 다시 시도해주세요.") from error

    return _parse_payload(answer.response_text)


def _parse_payload(raw_text: str) -> dict:
    payload = _extract_json_object(raw_text)

    try:
        kcal = int(round(float(payload["kcal_per_serving"])))
        serving_desc = str(payload["serving_desc"]).strip()
        if not serving_desc:
            raise ValueError("serving_desc 가 비어 있습니다.")
    except (KeyError, TypeError, ValueError) as error:
        raise NutritionEstimateError(
            "영양 정보를 해석하지 못했습니다. 다른 음식명으로 다시 시도해주세요."
        ) from error

    return {
        "kcal_per_serving": kcal,
        "serving_desc": serving_desc[:100],
        "carbs_g": _to_decimal(payload.get("carbs_g")),
        "protein_g": _to_decimal(payload.get("protein_g")),
        "fat_g": _to_decimal(payload.get("fat_g")),
    }


def _extract_json_object(raw_text: str) -> dict:
    start = raw_text.find("{")
    end = raw_text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise NutritionEstimateError(
            "영양 정보를 해석하지 못했습니다. 다른 음식명으로 다시 시도해주세요."
        )

    try:
        parsed = json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError as error:
        raise NutritionEstimateError(
            "영양 정보를 해석하지 못했습니다. 다른 음식명으로 다시 시도해주세요."
        ) from error

    if not isinstance(parsed, dict):
        raise NutritionEstimateError(
            "영양 정보를 해석하지 못했습니다. 다른 음식명으로 다시 시도해주세요."
        )

    return parsed


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
