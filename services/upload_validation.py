"""업로드 이미지 입력 검증.

predict 라우트가 모델에 넘기기 전에 크기·타입·디코드 가능 여부를 확인한다.
torch/YOLO에 의존하지 않으므로(=모델 로드 없이) 단위 테스트가 가능하다.

입력 오류는 여기서 4xx(HTTPException)로 끊고, 라우트의 500(내부 실패)과 분리한다.
"""

import io

from fastapi import HTTPException, status
from PIL import Image

# 휴대폰·웹 사진으로 올 수 있는 형식만 연다 — TIFF·BMP·PPM·GIF 같은 디코더를 업로드로 닿게 두지 않는다
# (2026-10-22: Pillow 12.3 의 CVE 24건이 대부분 그쪽이었다 — 13.0 이 고친 뒤에도 다음 취약점의 문을 좁혀 둔다).
# Gemini 로는 strip_metadata 가 JPEG 로 다시 저장해 보낸다.
# 휴대폰 카메라의 MPO(다중 사진 JPEG)는 JPEG 로 열린다 — 'MPO' 는 열기 형식 이름이 아니라 넣으면 그 뒤 형식이 KeyError 로
# 깨진다. HEIC 는 pillow-heif 가 없어 원래 열리지 않는다.
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP", "AVIF")


def validate_image_upload(content_type: str | None, data: bytes, max_bytes: int) -> None:
    """검증 실패 시 HTTPException을 던진다. 통과하면 None.

    - 용량 초과 → 413
    - 빈 파일 → 400
    - content-type이 image/* 가 아님 → 415
    - 이미지로 디코드 불가·허용 형식(ALLOWED_FORMATS) 밖 → 400
    """
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"이미지 용량이 너무 큽니다. {max_bytes // (1024 * 1024)}MB 이하로 업로드해주세요.",
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="빈 파일입니다. 이미지를 선택해주세요.",
        )

    # content-type은 클라이언트가 보낸 값이라 위조 가능하다 — 값이 있고 명백히 이미지가
    # 아닐 때만 조기 거부하고, 실제 판정은 아래 PIL 디코드가 담당한다.
    if content_type is not None and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="이미지 파일만 업로드할 수 있습니다.",
        )

    try:
        Image.open(io.BytesIO(data), formats=ALLOWED_FORMATS).verify()
    except Exception as error:  # PIL은 다양한 예외를 던진다 (UnidentifiedImageError 등).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효한 이미지 파일이 아닙니다. 다른 사진으로 다시 시도해주세요.",
        ) from error
