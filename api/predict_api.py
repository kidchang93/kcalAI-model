import logging

from fastapi import APIRouter, UploadFile, File, HTTPException

from log_utils import setup_level_logger
from schemas.gpt_schemas import GptError, GptResponse, GptAnswer
from schemas.predict_schema import PredictionResponse, ErrorResponse
from services.gpt_oss_service import answerByGptOss20B
from services.predict_service import predict_image

# setup_level_logger 는 LevelFilter 로 해당 레벨만 기록한다.
# INFO 로거로 error() 를 호출하면 레코드가 버려지므로 레벨별로 따로 만든다.
info_logger = setup_level_logger(logging.INFO)
error_logger = setup_level_logger(logging.ERROR)

router = APIRouter()

@router.post(
    "/predict",
    response_model=PredictionResponse,
    responses={500: {"model": ErrorResponse}}
)
async def predict(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        results = predict_image(image_bytes)
        info_logger.info(f"{file.filename} 정상 수집 완료")
        return {"predictions" : results}
    except Exception as e:
        # 내부 예외는 로그에만 남기고, 클라이언트에는 사용자용 메시지를 준다.
        error_logger.error(f"predict 실패 {file.filename}: {e!r}")
        raise HTTPException(
            status_code=500,
            detail="이미지 분석에 실패했습니다. 다른 사진으로 다시 시도해주세요.",
        ) from e

@router.post(
    "/gpt-predict",
    response_model=GptResponse,
    responses={500: {"model": GptError}}
)
async def gptPredict(request: GptAnswer):
    try:
        response=answerByGptOss20B(request)
        return response
    except Exception as e:
        error_logger.error(f"gpt-predict 실패: {e!r}")
        raise HTTPException(
            status_code=500,
            detail="칼로리 설명을 생성하지 못했습니다. 잠시 후 다시 시도해주세요.",
        ) from e
