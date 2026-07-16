import logging
import os
import time

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_current_user
from database import get_db
from log_utils import setup_level_logger
from models.auth_model import User
from schemas.predict_schema import PredictionResponse, ErrorResponse
from schemas.subscription_schema import PlanLimitErrorResponse
from services.gemini_vision_service import GEMINI_MODEL, VisionError, identify_food
from services.nutrition_service import prewarm_labels
from services.subscription_service import consume_vision_quota, refund_vision_quota
from services.upload_validation import validate_image_upload

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
        402: {"model": PlanLimitErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def predict(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 입력 검증은 try 밖에서 — 4xx가 아래 except로 뭉개지면 안 된다.
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"이미지 용량이 너무 큽니다. {MAX_UPLOAD_MB}MB 이하로 업로드해주세요.",
        )

    # size가 없을 수도 있으므로 상한+1까지만 읽어 메모리를 묶는다.
    image_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    validate_image_upload(file.content_type, image_bytes, MAX_UPLOAD_BYTES)

    # 요금제 일일 쿼터를 **먼저** 차감한다 (한도 초과면 PlanLimitError → 402 전역 핸들러).
    # 업로드 검증을 통과한 뒤에 차감해야, 형식 오류로 실패한 요청이 쿼터를 먹지 않는다.
    used, limit, usage_date = await run_in_threadpool(consume_vision_quota, db, current_user.id)

    # 비전 인식은 Gemini 단일 백엔드다(YOLO 제거). 블로킹 HTTP 호출이라 스레드풀에서 돌린다.
    started = time.perf_counter()
    try:
        results = await run_in_threadpool(identify_food, image_bytes, file.content_type)
    except VisionError as error:
        duration_ms = (time.perf_counter() - started) * 1000
        error_logger.error(
            f"predict fail backend=gemini duration_ms={duration_ms:.1f} "
            f"file={file.filename}: {error!r}"
        )
        # 사용자 잘못이 아닌 실패다. 선차감한 쿼터를 돌려준다 (차감할 때 쓴 날짜 그대로 — 자정
        # 을 걸친 요청이 엉뚱한 날의 카운터를 깎지 않도록).
        await run_in_threadpool(refund_vision_quota, db, current_user.id, usage_date)
        # 재시도 소진 등 일시 실패 → 재시도 가능한 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="음식 인식이 일시적으로 지연되고 있습니다. 잠시 후 다시 시도해주세요.",
        ) from error
    except Exception:
        # VisionError 로 감싸지지 않은 예외(예상 못 한 SDK 오류 등)로 500 이 나가더라도 쿼터는
        # 돌려준다 — 결과를 못 받은 사용자가 하루치 한도를 잃으면 안 된다.
        await run_in_threadpool(refund_vision_quota, db, current_user.id, usage_date)
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    # 관측 지표: 백엔드·모델·응답 시간·인식 음식 수·상위 음식을 구조적으로 남긴다.
    top = results[0] if results else None
    top_label = top.label if top else "-"
    top_score = float(top.score) if top else 0.0
    info_logger.info(
        f"predict ok backend=gemini model={GEMINI_MODEL} duration_ms={duration_ms:.1f} "
        f"food_count={len(results)} top_label={top_label} top_score={top_score:.4f} "
        f"quota={used}/{limit}"
    )

    # 인식된 전 음식 라벨을 응답 후 백그라운드로 조회·적재한다 — 사용자가 어느 음식을
    # 기록하든 estimate가 캐시 히트한다. 이미 있는 라벨은 LLM을 타지 않는다 (19장).
    background_tasks.add_task(prewarm_labels, [f.label for f in results])

    return {"foods": results, "vision_used": used, "vision_limit": limit}
