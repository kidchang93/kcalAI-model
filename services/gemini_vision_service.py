"""Gemini 비전 기반 음식 이름 식별 — 서버의 **단일** 이미지 인식 백엔드.

이미지 바이트 → Gemini(structured JSON) → 한글 요리명 후보 목록(Prediction). Gemini는
**이름 식별만** 담당하고, 칼로리·영양은 estimate 로직(nutrition_service)이 맡는다.
프롬프트는 반환 라벨이 mfds/curated 라벨에 매핑되도록 한식 요리명을 유도한다.

YOLO/torch는 제거됐고 폴백이 없다. 호출·재시도·파싱은 gemini_client가 담당하며,
최종 실패는 VisionError로 던져 predict 라우트가 503으로 응답한다. 키는 로그·응답에
절대 노출하지 않는다.
"""

import logging

from google.genai import types

from log_utils import setup_level_logger
from schemas.predict_schema import Prediction
from services.gemini_client import GEMINI_MODEL, GeminiError, ensure_api_key, generate_json

_MAX_CANDIDATES = 3

info_logger = setup_level_logger(logging.INFO)

_PROMPT = (
    "이 사진에 있는 '음식'을 식별하세요. 규칙:\n"
    "- 한국 음식 영양 DB에 있을 법한 **흔한 한글 요리명**으로 답하세요 "
    "(예: 김치찌개, 비빔밥, 제육볶음). 브랜드명·영어·재료명 단독은 피하고 요리명을 쓰세요.\n"
    "- 가능성이 높은 순으로 최대 3개 후보를 제시하세요.\n"
    "- confidence는 0~1 사이 숫자입니다.\n"
    "- 1인분 추정 무게(g)를 알 수 있으면 portion_g에 정수로, 모르면 null로 두세요.\n"
    "- 음식이 아니면 candidates를 빈 배열로 두세요."
)

# structured output 스키마. Gemini가 이 JSON 형태로만 응답한다.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "food_name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "portion_g": {"type": "integer", "nullable": True},
                },
                "required": ["food_name", "confidence"],
            },
        },
    },
    "required": ["candidates"],
}


class VisionError(Exception):
    """Gemini 비전 호출/파싱 실패(재시도 소진 포함). predict 라우트가 503으로 처리한다."""


def ensure_production_vision_config() -> None:
    # APP_ENV=production 일 때 main.py가 호출한다 — 폴백이 없으므로 키는 필수다.
    ensure_api_key()


def identify_food(image_bytes: bytes, mime_type: str | None = None) -> list[Prediction]:
    """이미지에서 음식명 후보(최대 3)를 Prediction(label=요리명, score=confidence)으로 반환.

    실패(타임아웃·429·API 오류·후보 없음)는 VisionError로 던진다. 키는 로그에 남기지 않는다.
    """
    try:
        data, duration_ms = generate_json(
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg"),
                _PROMPT,
            ],
            response_schema=_RESPONSE_SCHEMA,
        )
    except GeminiError as error:
        raise VisionError(str(error)) from error

    raw = data.get("candidates", [])
    predictions = [
        Prediction(label=str(c["food_name"]), score=float(c.get("confidence", 0.0)))
        for c in raw[:_MAX_CANDIDATES]
        if c.get("food_name")
    ]
    if not predictions:
        raise VisionError("Gemini가 음식 후보를 반환하지 않았습니다.")

    top = predictions[0]
    top_portion = raw[0].get("portion_g") if raw else None
    # 관측 로그(B9): 키·이미지 미노출, 결과만.
    info_logger.info(
        f"vision ok backend=gemini model={GEMINI_MODEL} duration_ms={duration_ms:.1f} "
        f"top_label={top.label} top_score={float(top.score):.4f} portion_g={top_portion}"
    )
    return predictions
