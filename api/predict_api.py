import logging
import os
import time

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status

from api.dependencies import get_current_user
from log_utils import setup_level_logger
from models.auth_model import User
from schemas.predict_schema import PredictionResponse, ErrorResponse
from services.predict_service import MODEL_WEIGHTS, predict_image
from services.upload_validation import validate_image_upload

# 관측 로그에 남길 모델 식별자 (가중치 파일명).
MODEL_NAME = os.path.basename(MODEL_WEIGHTS)

# setup_level_logger 는 LevelFilter 로 해당 레벨만 기록한다.
# INFO 로거로 error() 를 호출하면 레코드가 버려지므로 레벨별로 따로 만든다.
info_logger = setup_level_logger(logging.INFO)
error_logger = setup_level_logger(logging.ERROR)

# 업로드 상한 (기본 10MB). 리버스 프록시(nginx client_max_body_size)와 함께 방어한다.
MAX_UPLOAD_MB = int(os.getenv("PREDICT_MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

router = APIRouter()

@router.post(
    "/predict",
    response_model=PredictionResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def predict(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    # 입력 검증은 try 밖에서 — 4xx가 아래 except의 500으로 뭉개지면 안 된다.
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"이미지 용량이 너무 큽니다. {MAX_UPLOAD_MB}MB 이하로 업로드해주세요.",
        )

    # size가 없을 수도 있으므로 상한+1까지만 읽어 메모리를 묶는다.
    image_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    validate_image_upload(file.content_type, image_bytes, MAX_UPLOAD_BYTES)

    started = time.perf_counter()
    try:
        results = predict_image(image_bytes)
        duration_ms = (time.perf_counter() - started) * 1000
        # 관측 지표: 응답 시간·상위 예측·모델 버전을 구조적으로 남긴다.
        top = results[0] if results else None
        top_label = top.label if top else "-"
        top_score = float(top.score) if top else 0.0
        info_logger.info(
            f"predict ok model={MODEL_NAME} duration_ms={duration_ms:.1f} "
            f"top_label={top_label} top_score={top_score:.4f}"
        )
        return {"predictions" : results}
    except Exception as e:
        duration_ms = (time.perf_counter() - started) * 1000
        # 내부 예외는 로그에만 남기고, 클라이언트에는 사용자용 메시지를 준다.
        error_logger.error(
            f"predict fail model={MODEL_NAME} duration_ms={duration_ms:.1f} "
            f"file={file.filename}: {e!r}"
        )
        raise HTTPException(
            status_code=500,
            detail="이미지 분석에 실패했습니다. 다른 사진으로 다시 시도해주세요.",
        ) from e
