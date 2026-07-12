"""Gemini 비전 기반 음식 이름 식별.

이미지 바이트 → Gemini(structured JSON) → 한글 요리명 후보 목록(Prediction). Gemini는
**이름 식별만** 담당하고, 칼로리·영양은 기존 estimate 로직(식약처 DB 조회)이 계산한다.
프롬프트는 반환 라벨이 mfds/curated 라벨에 매핑되도록 한식 요리명을 유도한다.

`VISION_BACKEND=gemini`일 때만 predict 라우트가 이걸 호출한다(기본은 YOLO). 실패 시
라우트가 YOLO로 폴백한다. 키는 로그·응답에 절대 노출하지 않는다.
"""

import json
import logging
import os
import time

from google import genai
from google.genai import types

from log_utils import setup_level_logger
from schemas.predict_schema import Prediction

# flash-latest는 항상 현행 stable flash를 가리켜 모델 폐기(deprecation)에 안 깨진다.
# 재현성이 필요하면 env로 핀 버전(예: gemini-3.5-flash)을 지정한다.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Gemini 호출 타임아웃(ms). google-genai HttpOptions.timeout 단위는 밀리초.
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "15000"))
_MAX_CANDIDATES = 3

info_logger = setup_level_logger(logging.INFO)
error_logger = setup_level_logger(logging.ERROR)

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
    """Gemini 비전 호출/파싱 실패. predict 라우트가 YOLO 폴백 또는 500으로 처리한다."""


def ensure_production_vision_config() -> None:
    # APP_ENV=production 이고 VISION_BACKEND=gemini일 때 main.py가 호출한다.
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "VISION_BACKEND=gemini 운영에는 GEMINI_API_KEY를 설정해야 합니다."
        )


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise VisionError("GEMINI_API_KEY가 설정되지 않았습니다.")
        _client = genai.Client(api_key=api_key)
    return _client


def identify_food(image_bytes: bytes, mime_type: str | None = None) -> list[Prediction]:
    """이미지에서 음식명 후보(최대 3)를 Prediction(label=요리명, score=confidence)으로 반환.

    실패(타임아웃·429·API 오류·후보 없음)는 VisionError로 던진다. 키는 로그에 남기지 않는다.
    """
    client = _get_client()
    started = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg"),
                _PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
            ),
        )
    except Exception as error:  # API 오류·타임아웃·429 등. 키 노출 방지 위해 원문 대신 타입만.
        raise VisionError(f"Gemini 호출 실패: {type(error).__name__}") from error

    duration_ms = (time.perf_counter() - started) * 1000

    try:
        data = json.loads(response.text or "{}")
        raw = data.get("candidates", [])
    except (json.JSONDecodeError, AttributeError) as error:
        raise VisionError("Gemini 응답 파싱 실패") from error

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
