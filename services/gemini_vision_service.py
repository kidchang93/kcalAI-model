"""Gemini 비전 기반 음식 식별 — 서버의 **단일** 이미지 인식 백엔드.

이미지 바이트 → Gemini(structured JSON) → 사진에 있는 **서로 다른 음식** 목록(DetectedFood).
한 상에 밥·국·반찬이 함께 있으면 각각 별도 항목으로 돌려준다(같은 음식의 후보 나열이 아니다).
Gemini는 **이름·1인분 무게 식별만** 담당하고, 칼로리·영양은 estimate 로직(nutrition_service)이
맡는다. 프롬프트는 반환 라벨이 mfds/curated 라벨에 매핑되도록 한식 요리명을 유도한다.

YOLO/torch는 제거됐고 폴백이 없다. 호출·재시도·파싱은 gemini_client가 담당하며,
최종 실패는 VisionError로 던져 predict 라우트가 503으로 응답한다. 키는 로그·응답에
절대 노출하지 않는다.
"""

import io

from google.genai import types
from PIL import Image, ImageOps

from schemas.predict_schema import DetectedFood
from services.gemini_client import GeminiError, generate_json

# 한 사진에서 반환할 서로 다른 음식의 상한. 한 상 차림도 이 정도면 충분하고,
# 폭주 응답이 쿼터 없이 prewarm 부하로 번지는 것을 막는다.
_MAX_FOODS = 10

_PROMPT = (
    "이 사진에 있는 '음식'을 식별하세요. 규칙:\n"
    "- 사진에 있는 **서로 다른 음식을 각각** 식별하세요. 한 상에 밥·국·반찬처럼 여러 음식이 "
    "있으면 각각 별도 항목으로 나열하세요. 같은 음식의 후보를 여러 개 늘어놓지 말고, 실제로 "
    "존재하는 서로 다른 음식만 반환하세요.\n"
    "- 각 음식은 한국 음식 영양 DB에 있을 법한 **흔한 한글 요리명**으로 답하세요 "
    "(예: 김치찌개, 비빔밥, 제육볶음). 브랜드명·영어·재료명 단독은 피하고 요리명을 쓰세요.\n"
    "- confidence는 0~1 사이 숫자입니다.\n"
    "- 1인분 추정 무게(g)를 알 수 있으면 portion_g에 정수로, 모르면 null로 두세요.\n"
    "- 음식이 아니면 foods를 빈 배열로 두세요."
)

# structured output 스키마. Gemini가 이 JSON 형태로만 응답한다.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "foods": {
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
    "required": ["foods"],
}


class VisionError(Exception):
    """Gemini 비전 호출/파싱 실패(재시도 소진 포함). predict 라우트가 503으로 처리한다."""


def _as_portion(value: object) -> int | None:
    # structured output이 정수를 주게 돼 있으나, JSON 수치가 float로 올 여지를 방어한다.
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def strip_metadata(image_bytes: bytes) -> bytes:
    """촬영 위치·기기 같은 메타데이터(EXIF 등)를 지운 JPEG 를 돌려준다 — 제3자 AI 로는 픽셀만 보낸다.

    앨범 사진은 GPS 좌표를 품고 올 수 있다. 앱이 사진 AI 분석 동의에서 "촬영 정보는 지우고 보낸다"고
    약속하므로(App Store 5.1.2(i), 2026-10-05) 앱 설정에 기대지 않고 여기서 지운다. 회전 정보는
    픽셀에 반영한 뒤 버린다. 업로드 검증(validate_image_upload)이 Pillow 디코드를 통과시킨 바이트만
    오므로 여기서 열지 못할 일은 없다.
    """
    with Image.open(io.BytesIO(image_bytes)) as image:
        upright = ImageOps.exif_transpose(image).convert("RGB")
    out = io.BytesIO()
    upright.save(out, format="JPEG", quality=90)
    return out.getvalue()


def identify_food(image_bytes: bytes) -> list[DetectedFood]:
    """이미지에서 서로 다른 음식(최대 10)을 DetectedFood(label, score, portion_g)로 반환.

    한 사진에 밥·국·반찬이 함께 있으면 각각을 별도 항목으로 돌려준다 — 같은 음식의 후보
    나열이 아니다. 실패(타임아웃·429·API 오류·음식 없음)는 VisionError로 던진다.
    키는 로그에 남기지 않는다.
    """
    try:
        data, _duration_ms = generate_json(
            contents=[
                types.Part.from_bytes(data=strip_metadata(image_bytes), mime_type="image/jpeg"),
                _PROMPT,
            ],
            response_schema=_RESPONSE_SCHEMA,
        )
    except GeminiError as error:
        raise VisionError(str(error)) from error

    raw = data.get("foods", [])
    foods = [
        DetectedFood(
            label=str(item["food_name"]),
            score=float(item.get("confidence", 0.0)),
            portion_g=_as_portion(item.get("portion_g")),
        )
        for item in raw[:_MAX_FOODS]
        if item.get("food_name")
    ]
    if not foods:
        raise VisionError("Gemini가 음식을 인식하지 못했습니다.")

    # 성공 관측 로그는 predict 라우트의 `predict ok` 한 줄이다(쿼터까지 담는다).
    return foods
