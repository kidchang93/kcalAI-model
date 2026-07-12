"""services/upload_validation.py 테스트.

torch/YOLO 비의존 모듈이라 모델 로드 없이 검증 로직만 단위 테스트한다.
"""

import io

import pytest
from fastapi import HTTPException
from PIL import Image

from services.upload_validation import validate_image_upload

MAX_BYTES = 10 * 1024 * 1024


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 60, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_accepts_valid_png():
    validate_image_upload("image/png", _png_bytes(), MAX_BYTES)  # 예외 없음


def test_accepts_when_content_type_missing_but_decodable():
    # content-type이 없어도 PIL 디코드가 통과하면 허용한다.
    validate_image_upload(None, _png_bytes(), MAX_BYTES)


def test_rejects_oversized():
    data = b"\x00" * (MAX_BYTES + 1)
    with pytest.raises(HTTPException) as exc:
        validate_image_upload("image/jpeg", data, MAX_BYTES)
    assert exc.value.status_code == 413


def test_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        validate_image_upload("image/jpeg", b"", MAX_BYTES)
    assert exc.value.status_code == 400


def test_rejects_non_image_content_type():
    with pytest.raises(HTTPException) as exc:
        validate_image_upload("application/pdf", _png_bytes(), MAX_BYTES)
    assert exc.value.status_code == 415


def test_rejects_garbage_bytes_with_image_content_type():
    # content-type은 image라고 주장하지만 실제로는 이미지가 아님 → 디코드 실패 400.
    with pytest.raises(HTTPException) as exc:
        validate_image_upload("image/jpeg", b"this is not an image", MAX_BYTES)
    assert exc.value.status_code == 400


def test_rejects_garbage_bytes_without_content_type():
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(None, b"still not an image", MAX_BYTES)
    assert exc.value.status_code == 400
