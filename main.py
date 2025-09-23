import io

from PIL import Image
from fastapi import FastAPI, UploadFile, File
from starlette.responses import JSONResponse
from transformers import pipeline

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

        return JSONResponse(content={"predictions": results[:3]})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)