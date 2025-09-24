import io
import logging

from PIL import Image
from fastapi import FastAPI, UploadFile, File
from starlette.responses import JSONResponse
from transformers import pipeline

from log_utils import setup_level_logger

# 로거 생성
info_logger = setup_level_logger(logging.INFO)

app = FastAPI()
# Hugging Face 이미지 분류 파이프라인(음식 특화 모델)
classifier = pipeline(
    "image-classification",
    model="nateraw/food",
)


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    try:
        # 이미지 파일 읽기
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        # 모델 예측
        results = classifier(image)
        info_logger.info(f"{file} 정상 수집 완료")
        return JSONResponse(content={"predictions": results[:3]})
    except Exception as e:
        info_logger.info(f"exception 발생{file}")
        return JSONResponse(content={"error": str(e)}, status_code=500)