"""Gemini 호출 공용 어댑터 — 클라이언트 싱글톤 · 일시 오류 재시도 · structured JSON 파싱.

비전(음식명 식별)과 영양 추정이 같은 호출 규약을 쓰므로 여기로 모은다. 각 서비스는
프롬프트와 응답 스키마만 갖고, 전송·재시도·파싱은 이 모듈이 담당한다.

키는 로그·예외 메시지에 절대 노출하지 않는다 — 실패는 예외 **타입명**만 남긴다.
"""

import json
import logging
import os
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from log_utils import setup_level_logger

# flash-latest는 항상 현행 stable flash를 가리켜 모델 폐기(deprecation)에 안 깨진다.
# 재현성이 필요하면 env로 핀 버전(예: gemini-3.5-flash)을 지정한다.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Gemini 호출 타임아웃(ms). google-genai HttpOptions.timeout 단위는 밀리초.
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "15000"))
# 일시 오류 재시도: 최대 횟수와 백오프 기준 지연(초). 지연 = base * 2**attempt.
MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "2"))
_RETRY_BASE_DELAY = 0.5

error_logger = setup_level_logger(logging.ERROR)


class GeminiError(Exception):
    """Gemini 호출·파싱 실패(재시도 소진 포함). 호출한 서비스가 자기 예외로 감싼다."""


def _is_transient(error: Exception) -> bool:
    """재시도할 가치가 있는 일시 오류인가 — 429·5xx·타임아웃·네트워크."""
    if isinstance(error, genai_errors.ServerError):
        return True
    if isinstance(error, genai_errors.ClientError) and getattr(error, "code", None) == 429:
        return True
    name = type(error).__name__.lower()
    return "timeout" in name or "connect" in name


def ensure_api_key() -> None:
    """운영 기동 시 키 존재를 강제한다 (main.py). 폴백이 없으므로 키가 없으면 인식이 죽는다."""
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("운영에는 GEMINI_API_KEY를 설정해야 합니다.")


_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise GeminiError("GEMINI_API_KEY가 설정되지 않았습니다.")
        _client = genai.Client(api_key=api_key)
    return _client


def generate_json(
    contents: list,
    response_schema: dict,
    temperature: float | None = None,
) -> tuple[dict, float]:
    """structured JSON 응답을 받아 (파싱된 dict, 소요 ms)로 반환한다.

    일시 오류는 지수 백오프로 재시도하고, 최종 실패·파싱 실패는 GeminiError로 던진다.
    temperature=0 을 주면 같은 입력의 응답 변동이 줄어든다(영양 추정이 사용).
    """
    client = get_client()
    started = time.perf_counter()

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
        temperature=temperature,
    )

    response = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )
        except Exception as error:  # 키 노출 방지: 원문 대신 타입명만 로그/예외에 쓴다.
            if attempt < MAX_RETRIES and _is_transient(error):
                delay = _RETRY_BASE_DELAY * (2**attempt)
                error_logger.error(
                    f"gemini 일시 오류 재시도 {attempt + 1}/{MAX_RETRIES} "
                    f"({type(error).__name__}) delay={delay}s"
                )
                time.sleep(delay)
                continue
            raise GeminiError(f"Gemini 호출 실패: {type(error).__name__}") from error
        else:
            break  # 성공

    duration_ms = (time.perf_counter() - started) * 1000

    try:
        data = json.loads(response.text or "{}")
    except (json.JSONDecodeError, AttributeError) as error:
        raise GeminiError("Gemini 응답 파싱 실패") from error

    if not isinstance(data, dict):
        raise GeminiError("Gemini 응답이 객체가 아닙니다.")

    return data, duration_ms
