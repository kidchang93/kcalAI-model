import logging

from fastapi import APIRouter, UploadFile, File
from log_utils import setup_level_logger
from schemas.predict_schema import PredictionResponse, ErrorResponse
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

