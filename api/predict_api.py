import logging

from fastapi import APIRouter, UploadFile, File, HTTPException

from log_utils import setup_level_logger
from schemas.gpt_schemas import GptError, GptResponse, GptAnswer
from schemas.predict_schema import PredictionResponse, ErrorResponse
from services.gpt_oss_service import answerByGptOss20B
from services.predict_service import predict_image

info_logger = setup_level_logger(logging.INFO)
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
        info_logger.error(f"exception 발생 {file.filename}: {str(e)}")
        return {"error": str(e)}

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
        raise HTTPException(status_code=500, detail=str(e))